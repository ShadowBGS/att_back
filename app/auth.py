from __future__ import annotations

from dataclasses import dataclass
import logging

import firebase_admin
from fastapi import Depends, Header, HTTPException
from firebase_admin import auth, credentials

from .config import get_settings


@dataclass(frozen=True)
class AuthContext:
    firebase_uid: str
    email: str | None
    name: str | None


_app_initialized = False
logger = logging.getLogger(__name__)


def _init_firebase() -> None:
    global _app_initialized
    if _app_initialized:
        return

    settings = get_settings()

    if settings.firebase_service_account_json is not None:
        cred = credentials.Certificate(settings.firebase_service_account_json)
        firebase_admin.initialize_app(cred)
        _app_initialized = True
        return

    if settings.firebase_service_account_file:
        cred = credentials.Certificate(settings.firebase_service_account_file)
        firebase_admin.initialize_app(cred)
        _app_initialized = True
        return

    raise RuntimeError(
        "Firebase Admin credentials not configured. Set FIREBASE_SERVICE_ACCOUNT_FILE or FIREBASE_SERVICE_ACCOUNT_JSON"
    )


def get_auth_context(authorization: str | None = Header(default=None)) -> AuthContext:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    try:
        _init_firebase()
    except Exception as e:
        logger.exception("Firebase Admin initialization failed")
        raise HTTPException(
            status_code=500,
            detail="Server auth is not configured (Firebase Admin init failed).",
        ) from e

    try:
        decoded = auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Token missing uid")

    return AuthContext(
        firebase_uid=firebase_uid,
        email=decoded.get("email"),
        name=decoded.get("name"),
    )


def require_auth(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    return ctx
