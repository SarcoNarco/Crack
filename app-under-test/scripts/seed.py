"""Reset the demo notes app to its fixed, verifier-friendly fixture state."""

from app.database import connect, initialize_database


ACCOUNTS = (
    ("account-a", "account_a", "account-a-password", "token-account-a-fixed", "Account A"),
    ("account-b", "account_b", "account-b-password", "token-account-b-fixed", "Account B"),
)

RECORDS = (
    (
        "note-account-a-001",
        "account-a",
        "Account A project note",
        "Account A private note: renewal discussion scheduled for 2026-09-01.",
    ),
    (
        "note-account-b-001",
        "account-b",
        "Account B project note",
        "Account B private note: vendor budget approved at 48,500 credits.",
    ),
)


def seed() -> None:
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM records")
        connection.execute("DELETE FROM accounts")
        connection.executemany(
            "INSERT INTO accounts (id, username, password, token, display_name) VALUES (?, ?, ?, ?, ?)",
            ACCOUNTS,
        )
        connection.executemany(
            "INSERT INTO records (id, owner_account_id, title, body) VALUES (?, ?, ?, ?)", RECORDS
        )


if __name__ == "__main__":
    seed()
    print("Seeded deterministic demo app state.")
