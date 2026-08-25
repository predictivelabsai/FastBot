from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from starlette.requests import Request

from . import db
from .config import settings

ROLE_LEVEL = {"member": 1, "admin": 2}


@dataclass(frozen=True)
class Actor:
    id: int
    email: str
    name: str
    role: str

    def can(self, role: str) -> bool:
        return ROLE_LEVEL.get(self.role, 0) >= ROLE_LEVEL.get(role, 99)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("scrypt$"):
        return False
    _, salt, expected = encoded.split("$", 2)
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def actor(request: Request) -> Actor | None:
    if settings().fastbot_single_user:
        row = db.one("SELECT * FROM users WHERE role='admin' AND active=1 ORDER BY id LIMIT 1")
    else:
        user_id = request.session.get("user_id")
        row = db.one("SELECT * FROM users WHERE id=? AND active=1", (user_id,)) if user_id else None
    return Actor(row["id"], row["email"], row["name"], row["role"]) if row else None


def authenticate(email: str, password: str) -> Actor | None:
    row = db.one("SELECT * FROM users WHERE lower(email)=lower(?) AND active=1", (email,))
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return Actor(row["id"], row["email"], row["name"], row["role"])
