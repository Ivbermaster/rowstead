import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from app.config import settings
from app.db import get_db
from app.models import User

COOKIE = "batchflow_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return f"pbkdf2_sha256$600000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def serializer():
    if len(settings.session_secret) < 32:
        raise RuntimeError(
            "Set SESSION_SECRET to at least 32 random characters before starting API"
        )
    return URLSafeTimedSerializer(settings.session_secret, salt="batchflow-session-v1")


def session_data(request: Request) -> dict:
    try:
        return serializer().loads(request.cookies.get(COOKIE, ""), max_age=12 * 3600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Sign in to continue") from None


def current_user(request: Request, db=Depends(get_db)) -> User:
    data = session_data(request)
    user = db.scalar(select(User).where(User.id == data.get("uid")))
    if user is None:
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(token, data.get("csrf", "")):
            raise HTTPException(403, "Invalid CSRF token; reload the page")
    return user
