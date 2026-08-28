from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed import seed


TEACHER = {"Authorization": "Bearer token-teacher-fixed"}
STUDENT_A = {"Authorization": "Bearer token-student-a-fixed"}
STUDENT_B = {"Authorization": "Bearer token-student-b-fixed"}
STUDENT_A_SUBMISSION = "submission-student-a-001"
STUDENT_B_SUBMISSION = "submission-student-b-001"
STUDENT_A_GRADE = "grade-student-a-001"


def test_seed_is_idempotent_and_student_lists_are_isolated(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()
    seed()

    with TestClient(app) as client:
        student_a = client.get("/submissions/mine", headers=STUDENT_A)
        student_b = client.get("/submissions/mine", headers=STUDENT_B)

    assert [submission["submission_id"] for submission in student_a.json()["submissions"]] == [STUDENT_A_SUBMISSION]
    assert [submission["submission_id"] for submission in student_b.json()["submissions"]] == [STUDENT_B_SUBMISSION]
    assert all(submission["student_id"] == "student-a" for submission in student_a.json()["submissions"])
    assert all(submission["student_id"] == "student-b" for submission in student_b.json()["submissions"])


def test_exact_id_cross_student_detail_is_the_single_intended_read_defect(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()

    with TestClient(app) as client:
        response = client.get(f"/submissions/{STUDENT_B_SUBMISSION}/grade", headers=STUDENT_A)

    assert response.status_code == 200
    assert response.json()["submission_id"] == STUDENT_B_SUBMISSION
    assert response.json()["student_id"] == "student-b"
    assert response.json()["grade_id"] == "grade-student-b-001"


def test_grade_writes_enforce_teacher_role_and_owned_grade(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()

    with TestClient(app) as client:
        student_review = client.post(f"/grades/{STUDENT_A_GRADE}/review", headers=STUDENT_A)
        student_publish = client.post(f"/grades/{STUDENT_A_GRADE}/publish", headers=STUDENT_B)
        teacher_list = client.get("/grades/mine", headers=TEACHER)
        student_list = client.get("/grades/mine", headers=STUDENT_A)

    assert student_review.status_code == 403
    assert student_publish.status_code == 403
    assert student_list.status_code == 403
    assert [grade["grade_id"] for grade in teacher_list.json()["grades"]] == [
        "grade-student-a-001", "grade-student-b-001"
    ]


def test_reviewed_grade_can_be_published(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()

    with TestClient(app) as client:
        reviewed = client.post(f"/grades/{STUDENT_A_GRADE}/review", headers=TEACHER)
        published = client.post(f"/grades/{STUDENT_A_GRADE}/publish", headers=TEACHER)

    assert reviewed.json() == {"grade_id": STUDENT_A_GRADE, "previous_state": "draft", "state": "reviewed"}
    assert published.json() == {"grade_id": STUDENT_A_GRADE, "previous_state": "reviewed", "state": "published"}


def test_draft_to_published_is_the_one_intentional_invalid_transition(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()

    with TestClient(app) as client:
        published = client.post(f"/grades/{STUDENT_A_GRADE}/publish", headers=TEACHER)
        repeated_publish = client.post(f"/grades/{STUDENT_A_GRADE}/publish", headers=TEACHER)
        terminal_review = client.post(f"/grades/{STUDENT_A_GRADE}/review", headers=TEACHER)

    assert published.json() == {"grade_id": STUDENT_A_GRADE, "previous_state": "draft", "state": "published"}
    assert repeated_publish.status_code == 409
    assert terminal_review.status_code == 409
