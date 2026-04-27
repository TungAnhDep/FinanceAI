"""Apply schema.sql to the configured Postgres database.

Run this once on setup, after schema changes, or as part of deploy.
NOT run per-request — see the audit fix to db.py.
"""

from database.db import NewsDB


def main():
    with NewsDB() as db:
        db.ensure_schema()
    print("Schema applied successfully.")


if __name__ == "__main__":
    main()
