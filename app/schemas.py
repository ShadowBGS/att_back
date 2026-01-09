from __future__ import annotations

from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    role: str  # 'student' or 'lecturer'


class BootstrapResponse(BaseModel):
    firebase_uid: str
    role: str
    profile_completed: bool
    is_new_user: bool


class CompleteProfileRequest(BaseModel):
    external_id: str
    department: str
    name: str | None = None


class SyncOp(BaseModel):
    op_id: str
    entity: str
    op: str  # upsert | delete
    entity_id: str
    payload: dict
    client_ts: str | None = None


class SyncPushRequest(BaseModel):
    ops: list[SyncOp]


class SyncPushResult(BaseModel):
    op_id: str
    ok: bool
    error: str | None = None


class SyncPushResponse(BaseModel):
    results: list[SyncPushResult]
    cursor: str | None = None


class SyncPullResponse(BaseModel):
    cursor: str | None = None
    changes: dict
