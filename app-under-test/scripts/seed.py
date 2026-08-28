"""Reset the synthetic school portal to its fixed verifier-friendly fixture state."""

from app.database import connect, initialize_database


PEOPLE = (
    ("teacher-001", "teacher", "token-teacher-fixed", "Teacher"),
    ("student-a", "student", "token-student-a-fixed", "Student A"),
    ("student-b", "student", "token-student-b-fixed", "Student B"),
)
CLASSES = (("class-science-101", "teacher-001", "Science 101"),)
ASSIGNMENTS = (("assignment-ecosystems-001", "class-science-101", "Ecosystems reflection"),)
SUBMISSIONS = (
    ("submission-student-a-001", "assignment-ecosystems-001", "student-a", "Student A private reflection."),
    ("submission-student-b-001", "assignment-ecosystems-001", "student-b", "Student B private reflection."),
)
GRADES = (
    ("grade-student-a-001", "submission-student-a-001", "teacher-001", "Clear analysis.", "draft"),
    ("grade-student-b-001", "submission-student-b-001", "teacher-001", "Strong use of evidence.", "draft"),
)


def seed() -> None:
    """Replace only the disposable app's old and current local fixture schema."""
    initialize_database()
    with connect() as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS work_items;
            DROP TABLE IF EXISTS records;
            DROP TABLE IF EXISTS accounts;
            DROP TABLE IF EXISTS grades;
            DROP TABLE IF EXISTS submissions;
            DROP TABLE IF EXISTS assignments;
            DROP TABLE IF EXISTS classes;
            DROP TABLE IF EXISTS people;
            """
        )
    initialize_database()
    with connect() as connection:
        connection.executemany(
            "INSERT INTO people (id, role, token, display_name) VALUES (?, ?, ?, ?)", PEOPLE
        )
        connection.executemany(
            "INSERT INTO classes (id, teacher_id, title) VALUES (?, ?, ?)", CLASSES
        )
        connection.executemany(
            "INSERT INTO assignments (id, class_id, title) VALUES (?, ?, ?)", ASSIGNMENTS
        )
        connection.executemany(
            "INSERT INTO submissions (id, assignment_id, student_id, body) VALUES (?, ?, ?, ?)",
            SUBMISSIONS,
        )
        connection.executemany(
            "INSERT INTO grades (id, submission_id, teacher_id, feedback, state) VALUES (?, ?, ?, ?, ?)",
            GRADES,
        )


if __name__ == "__main__":
    seed()
    print("Seeded deterministic synthetic school portal state.")
