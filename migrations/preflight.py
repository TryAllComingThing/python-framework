"""Online migration safety checks that must run before schema changes."""

from sqlalchemy import Connection, text


def assert_username_keys_unique(connection: Connection) -> None:
    """Fail with actionable diagnostics before lower(username) is indexed.

    The check is intentionally online-only and non-destructive. Fresh databases
    do not have ``sf_users`` yet, so the baseline upgrade skips this preflight.
    """
    table_exists: object = connection.execute(text("SELECT to_regclass('sf_users')")).scalar_one()
    if table_exists is None:
        return
    duplicates = connection.execute(
        text(
            "SELECT lower(username) AS username_key, count(*) AS duplicate_count "
            "FROM sf_users GROUP BY lower(username) "
            "HAVING count(*) > 1 ORDER BY username_key LIMIT 20"
        )
    ).all()
    if duplicates:
        rendered = ", ".join(f"{row.username_key!r} ({row.duplicate_count})" for row in duplicates)
        raise RuntimeError(
            f"Username case-insensitive duplicates must be resolved before migration: {rendered}"
        )
