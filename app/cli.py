import argparse
from getpass import getpass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.bootstrap import create_first_admin


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-admin", help="Create the first administrator account")
    args = parser.parse_args()

    if args.command == "create-admin":
        settings = get_settings()
        if not settings.database_url:
            parser.error("DATABASE_URL must be configured")
        if not settings.jwt_secret_key:
            parser.error("NEXORA_JWT_SECRET_KEY must be configured")
        name = input("Admin name: ").strip()
        email = input("Admin email: ").strip().lower()
        password = getpass("Admin password (minimum 8 characters): ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            parser.error("Passwords do not match")
        if len(password) < 8:
            parser.error("Password must contain at least 8 characters")
        with Session(get_engine()) as session:
            try:
                user = create_first_admin(
                    session,
                    name=name,
                    email=email,
                    password=password,
                )
            except ValueError as error:
                parser.error(str(error))
        print(f"Administrator account created for {user.email}")


if __name__ == "__main__":
    main()
