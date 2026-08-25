from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .config import settings


def _cipher() -> Fernet:
    digest = hashlib.sha256(settings().fastbot_session_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def store(name: str, kind: str, value: str, user_id: int | None = None) -> int:
    if not value:
        raise ValueError("Credential value cannot be empty")
    encrypted = _cipher().encrypt(value.encode())
    existing = db.one("SELECT id FROM credentials WHERE name=?", (name,))
    if existing:
        db.execute("UPDATE credentials SET kind=?,ciphertext=?,updated_at=? WHERE id=?",
                   (kind, encrypted, db.now(), existing["id"]))
        credential_id = existing["id"]
    else:
        credential_id = db.execute(
            "INSERT INTO credentials(name,kind,ciphertext,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (name, kind, encrypted, user_id, db.now(), db.now()),
        )
    db.audit("credential.stored", detail={"credential_id": credential_id, "name": name, "kind": kind})
    return credential_id


def reveal(credential_id: int) -> str:
    row = db.one("SELECT ciphertext FROM credentials WHERE id=?", (credential_id,))
    if not row:
        raise KeyError("Credential not found")
    try:
        return _cipher().decrypt(row["ciphertext"]).decode()
    except InvalidToken as exc:
        raise RuntimeError("Credential encryption key does not match") from exc


def metadata() -> list[dict]:
    return db.rows("SELECT id,name,kind,created_at,updated_at FROM credentials ORDER BY name")
