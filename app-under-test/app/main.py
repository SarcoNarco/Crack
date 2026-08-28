"""A tiny school portal used only as Crack's disposable local target."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status

from .database import connect, initialize_database


def current_person(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ")
    with connect() as connection:
        person = connection.execute(
            "SELECT id, role, display_name FROM people WHERE token = ?", (token,)
        ).fetchone()
    if person is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return dict(person)


def _require_role(person: dict[str, str], role: str) -> None:
    if person["role"] != role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not allowed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Synthetic School Portal", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/submissions/mine")
def get_my_submissions(person: dict[str, str] = Depends(current_person)) -> dict[str, list[dict[str, str]]]:
    """Return only the authenticated student's own submissions."""
    _require_role(person, "student")
    with connect() as connection:
        submissions = connection.execute(
            """
            SELECT submissions.id AS submission_id, submissions.assignment_id, submissions.student_id,
                   grades.id AS grade_id, grades.state
            FROM submissions
            JOIN grades ON grades.submission_id = submissions.id
            WHERE submissions.student_id = ?
            ORDER BY submissions.id
            """,
            (person["id"],),
        ).fetchall()
    return {"submissions": [dict(submission) for submission in submissions]}


@app.get("/submissions/{submission_id}/grade")
def get_submission_grade(
    submission_id: str, person: dict[str, str] = Depends(current_person)
) -> dict[str, str]:
    """Return one student submission and grade detail.

    The deliberately seeded defect is here: an authenticated student is checked,
    but the submission's student_id is not compared with that caller.
    """
    _require_role(person, "student")
    with connect() as connection:
        detail = connection.execute(
            """
            SELECT submissions.id AS submission_id, submissions.assignment_id, submissions.student_id,
                   submissions.body AS submission_body, grades.id AS grade_id,
                   grades.feedback, grades.state
            FROM submissions
            JOIN grades ON grades.submission_id = submissions.id
            WHERE submissions.id = ?
            """,
            (submission_id,),
        ).fetchone()
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return dict(detail)


def _teacher_grade(grade_id: str, teacher_id: str) -> dict[str, str]:
    with connect() as connection:
        grade = connection.execute(
            "SELECT id, submission_id, teacher_id, feedback, state FROM grades WHERE id = ? AND teacher_id = ?",
            (grade_id, teacher_id),
        ).fetchone()
    if grade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found")
    return dict(grade)


@app.get("/grades/mine")
def get_my_grades(person: dict[str, str] = Depends(current_person)) -> dict[str, list[dict[str, str]]]:
    """Return only the fixed teacher's grading work list."""
    _require_role(person, "teacher")
    with connect() as connection:
        grades = connection.execute(
            "SELECT id AS grade_id, submission_id, teacher_id, state FROM grades WHERE teacher_id = ? ORDER BY id",
            (person["id"],),
        ).fetchall()
    return {"grades": [dict(grade) for grade in grades]}


@app.post("/grades/{grade_id}/review")
def review_grade(grade_id: str, person: dict[str, str] = Depends(current_person)) -> dict[str, str]:
    """Advance only a teacher-owned draft grade to reviewed."""
    _require_role(person, "teacher")
    grade = _teacher_grade(grade_id, person["id"])
    if grade["state"] != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft grades can be reviewed")
    with connect() as connection:
        connection.execute("UPDATE grades SET state = 'reviewed' WHERE id = ?", (grade_id,))
    return {"grade_id": grade_id, "previous_state": "draft", "state": "reviewed"}


@app.post("/grades/{grade_id}/publish")
def publish_grade(grade_id: str, person: dict[str, str] = Depends(current_person)) -> dict[str, str]:
    """Publish a teacher-owned grade; intentionally missing the reviewed-state check."""
    _require_role(person, "teacher")
    grade = _teacher_grade(grade_id, person["id"])
    if grade["state"] == "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Published grades are terminal")
    # Intentional Sprint 14 defect: a draft grade incorrectly bypasses review here.
    with connect() as connection:
        connection.execute("UPDATE grades SET state = 'published' WHERE id = ?", (grade_id,))
    return {"grade_id": grade_id, "previous_state": grade["state"], "state": "published"}
