"""Password hashing (scrypt) and HMAC-signed bearer tokens."""

import base64
import hashlib
import hmac
import os
import time

from fastapi import Header, HTTPException

from .db import SECRET_KEY, get_user_by_email, create_user

TOKEN_TTL_SEC = 30 * 24 * 3600
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD_LEN = 8


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt,
                          n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()


def register(email: str, password: str) -> int:
    if "@" not in email or len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"valid email and password (min {MIN_PASSWORD_LEN} chars) required")
    if get_user_by_email(email):
        raise HTTPException(409, "email already registered")
    salt = os.urandom(16)
    return create_user(email, _hash_password(password, salt), salt.hex())


def login(email: str, password: str) -> str:
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(401, "invalid credentials")
    expected = _hash_password(password, bytes.fromhex(user["salt"]))
    if not hmac.compare_digest(expected, user["pw_hash"]):
        raise HTTPException(401, "invalid credentials")
    return make_token(user["id"])


def make_token(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + TOKEN_TTL_SEC}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def current_user(authorization: str = Header(default="")) -> int:
    """FastAPI dependency: returns the authenticated user id."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = base64.urlsafe_b64decode(token).decode()
        user_id, expiry, sig = payload.rsplit(":", 2)
        expected = hmac.new(SECRET_KEY.encode(), f"{user_id}:{expiry}".encode(),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(expiry) < time.time():
            raise ValueError
        return int(user_id)
    except Exception:
        raise HTTPException(401, "not logged in") from None
