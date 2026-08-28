from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed import seed


TEACHER = {"Authorization": "Bearer token-teacher-fixed"}
STUDENT_A = {"Authorization": "Bearer token-student-a-fixed"}
STUDENT_B = {"Authorization": "Bearer token-student-b-fixed"}


def _seeded_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "portal.db"))
    seed()
    return TestClient(app)


def test_portal_root_and_local_assets_are_served(monkeypatch, tmp_path) -> None:
    with _seeded_client(monkeypatch, tmp_path) as client:
        root = client.get("/")
        stylesheet = client.get("/static/portal.css")
        script = client.get("/static/portal.js")

    assert root.status_code == stylesheet.status_code == script.status_code == 200
    assert 'href="/static/portal.css"' in root.text
    assert 'src="/static/portal.js"' in root.text
    assert "Synthetic demo data" in root.text
    assert "http://" not in root.text + stylesheet.text + script.text
    assert "https://" not in root.text + stylesheet.text + script.text


def test_portal_used_student_api_returns_only_each_students_own_visible_data(monkeypatch, tmp_path) -> None:
    with _seeded_client(monkeypatch, tmp_path) as client:
        student_a = client.get("/submissions/mine", headers=STUDENT_A)
        student_b = client.get("/submissions/mine", headers=STUDENT_B)

    assert student_a.status_code == student_b.status_code == 200
    assert student_a.json() == {
        "submissions": [{
            "submission_id": "submission-student-a-001",
            "assignment_id": "assignment-ecosystems-001",
            "student_id": "student-a",
            "submission_body": "Student A private reflection.",
            "assignment_title": "Ecosystems reflection",
            "class_title": "Science 101",
            "grade_status": "pending",
        }]
    }
    assert student_b.json() == {
        "submissions": [{
            "submission_id": "submission-student-b-001",
            "assignment_id": "assignment-ecosystems-001",
            "student_id": "student-b",
            "submission_body": "Student B private reflection.",
            "assignment_title": "Ecosystems reflection",
            "class_title": "Science 101",
            "grade_status": "pending",
        }]
    }


def test_portal_students_see_only_own_published_feedback(monkeypatch, tmp_path) -> None:
    with _seeded_client(monkeypatch, tmp_path) as client:
        published = client.post("/grades/grade-student-a-001/publish", headers=TEACHER)
        student_a = client.get("/submissions/mine", headers=STUDENT_A)
        student_b = client.get("/submissions/mine", headers=STUDENT_B)

    assert published.status_code == 200
    assert student_a.json()["submissions"] == [{
        "submission_id": "submission-student-a-001",
        "assignment_id": "assignment-ecosystems-001",
        "student_id": "student-a",
        "submission_body": "Student A private reflection.",
        "assignment_title": "Ecosystems reflection",
        "class_title": "Science 101",
        "grade_status": "published",
        "grade_id": "grade-student-a-001",
        "feedback": "Clear analysis.",
    }]
    assert student_b.json()["submissions"] == [{
        "submission_id": "submission-student-b-001",
        "assignment_id": "assignment-ecosystems-001",
        "student_id": "student-b",
        "submission_body": "Student B private reflection.",
        "assignment_title": "Ecosystems reflection",
        "class_title": "Science 101",
        "grade_status": "pending",
    }]


def test_portal_teacher_queue_has_synthetic_student_labels_feedback_and_lifecycle(monkeypatch, tmp_path) -> None:
    with _seeded_client(monkeypatch, tmp_path) as client:
        response = client.get("/grades/mine", headers=TEACHER)

    assert response.status_code == 200
    assert response.json()["grades"] == [
        {
            "grade_id": "grade-student-a-001",
            "submission_id": "submission-student-a-001",
            "teacher_id": "teacher-001",
            "feedback": "Clear analysis.",
            "state": "draft",
            "student_name": "Student A",
            "submission_body": "Student A private reflection.",
            "assignment_title": "Ecosystems reflection",
            "class_title": "Science 101",
        },
        {
            "grade_id": "grade-student-b-001",
            "submission_id": "submission-student-b-001",
            "teacher_id": "teacher-001",
            "feedback": "Strong use of evidence.",
            "state": "draft",
            "student_name": "Student B",
            "submission_body": "Student B private reflection.",
            "assignment_title": "Ecosystems reflection",
            "class_title": "Science 101",
        },
    ]


def test_portal_grade_mutations_stay_teacher_only(monkeypatch, tmp_path) -> None:
    with _seeded_client(monkeypatch, tmp_path) as client:
        student_review = client.post("/grades/grade-student-a-001/review", headers=STUDENT_A)
        student_publish = client.post("/grades/grade-student-a-001/publish", headers=STUDENT_B)
        teacher_review = client.post("/grades/grade-student-a-001/review", headers=TEACHER)

    assert student_review.status_code == student_publish.status_code == 403
    assert teacher_review.json() == {
        "grade_id": "grade-student-a-001",
        "previous_state": "draft",
        "state": "reviewed",
    }


def test_portal_javascript_uses_only_normal_list_apis_and_local_assets() -> None:
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    script = (static / "portal.js").read_text(encoding="utf-8")

    assert "'/submissions/mine'" in script
    assert "/submissions/${" not in script
    assert "/grade'" not in script
    assert "submission-student-a-001" not in script
    assert "submission-student-b-001" not in script
