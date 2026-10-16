import argparse
import getpass
import os

from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User


def main():
    parser = argparse.ArgumentParser(description="Rowstead administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("login")
    args = parser.parse_args()
    if args.command == "create-user":
        password = os.getenv("BATCHFLOW_ADMIN_PASSWORD") or getpass.getpass(
            "Password (12+ characters): "
        )
        if len(password) < 12 or len(password) > 1024:
            parser.error("Password must be 12–1024 characters")
        if not args.login.strip() or len(args.login) > 100:
            parser.error("Login must be 1–100 characters")
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.login == args.login)):
                parser.error("User already exists")
            db.add(User(login=args.login, password_hash=hash_password(password)))
            db.commit()
        print("User created")


if __name__ == "__main__":
    main()
