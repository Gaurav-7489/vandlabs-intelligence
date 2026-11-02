"""Operator CLI. Usage: python -m app.cli create-platform-admin <email>"""
import sys

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "create-platform-admin":
        print("usage: python -m app.cli create-platform-admin <email>")
        raise SystemExit(2)
    email = sys.argv[2].strip().lower()
    eng = create_engine(get_settings().migration_database_url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO users (email, is_platform_admin) VALUES (:e, true) "
                       "ON CONFLICT (email) DO UPDATE SET is_platform_admin = true"), {"e": email})
        c.execute(text("INSERT INTO audit_events (action, outcome, metadata) VALUES ('platform.admin_granted', 'success', cast(:m as jsonb))"),
                  {"m": f'{{"email": "{email}"}}'})
    print(f"platform admin ensured for {email}")


if __name__ == "__main__":
    main()
