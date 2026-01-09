from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .auth import AuthContext, require_auth
from .config import get_settings
from .db import get_db
from .models import User
from .schemas import (
    BootstrapRequest,
    BootstrapResponse,
    CompleteProfileRequest,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncPushResult,
)

settings = get_settings()

logger = logging.getLogger(__name__)

app = FastAPI(title="Attendance Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/auth/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    body: BootstrapRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> BootstrapResponse:
    role = body.role.strip().lower()
    if role not in {"student", "lecturer"}:
        role = "student"

    try:
        existing = (
            db.query(User)
            .filter(User.firebase_uid == ctx.firebase_uid)
            .one_or_none()
        )

        is_new = existing is None

        if existing:
            existing.email = ctx.email
            existing.name = ctx.name
            existing.role = role
            db.commit()
            db.refresh(existing)
            return BootstrapResponse(
                firebase_uid=existing.firebase_uid,
                role=existing.role,
                profile_completed=existing.profile_completed,
                is_new_user=False,
            )

        stmt = (
            insert(User)
            .values(
                firebase_uid=ctx.firebase_uid,
                email=ctx.email,
                name=ctx.name,
                role=role,
                profile_completed=False,
            )
            .returning(User)
        )
        row = db.execute(stmt).scalar_one()
        db.commit()
        return BootstrapResponse(
            firebase_uid=row.firebase_uid,
            role=row.role,
            profile_completed=row.profile_completed,
            is_new_user=is_new,
        )
    except SQLAlchemyError as e:
        logger.exception("Bootstrap DB error")
        raise HTTPException(
            status_code=500,
            detail="Bootstrap failed (database error). Check DATABASE_URL and run migrations.",
        ) from e
    except Exception as e:
        logger.exception("Bootstrap unexpected error")
        raise HTTPException(status_code=500, detail="Bootstrap failed (server error).") from e


@app.post("/profile/complete")
def complete_profile(
    body: CompleteProfileRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    try:
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.external_id = body.external_id.strip()
        user.department = body.department.strip()
        user.profile_completed = True
        
        # Create Student or Lecturer record
        from app.models import Student, Lecturer
        
        if user.role == 'student':
            # Check if student record already exists
            existing_student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
            if not existing_student:
                student = Student(
                    user_id=user.id,
                    matric_no=user.external_id,
                    department=user.department,
                    level=None  # Can be set later
                )
                db.add(student)
                logger.info(f"Created student record for user {user.id} with matric_no {user.external_id}")
            else:
                # Update existing student record
                existing_student.matric_no = user.external_id
                existing_student.department = user.department
                logger.info(f"Updated student record for user {user.id}")
        
        elif user.role == 'lecturer':
            # Check if lecturer record already exists
            existing_lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
            if not existing_lecturer:
                lecturer = Lecturer(
                    user_id=user.id,
                    department=user.department
                )
                db.add(lecturer)
                logger.info(f"Created lecturer record for user {user.id}")
            else:
                # Update existing lecturer record
                existing_lecturer.department = user.department
                logger.info(f"Updated lecturer record for user {user.id}")
        
        db.commit()
        return {"ok": True, "profile_completed": True}
    except SQLAlchemyError as e:
        logger.exception("Complete profile DB error")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Profile update failed (database error).",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Complete profile unexpected error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Profile update failed (server error).") from e


@app.get("/profile/info")
def profile_info(
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Get user profile info and check if role-specific record exists"""
    try:
        from app.models import Student, Lecturer
        
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        role_record_exists = False
        role_info = None

        if user.role == 'student':
            student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
            if student:
                role_record_exists = True
                role_info = {
                    "student_id": student.student_id,
                    "matric_no": student.matric_no,
                    "level": student.level,
                }
        elif user.role == 'lecturer':
            lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
            if lecturer:
                role_record_exists = True
                role_info = {
                    "lecturer_id": lecturer.lecturer_id,
                }

        return {
            "user_id": str(user.id),
            "firebase_uid": user.firebase_uid,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "external_id": user.external_id,
            "department": user.department,
            "profile_completed": user.profile_completed,
            "role_record_exists": role_record_exists,
            "role_info": role_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Profile info error")
        raise HTTPException(status_code=500, detail="Failed to retrieve profile info.") from e


@app.post("/sync/push", response_model=SyncPushResponse)
def sync_push(
    body: SyncPushRequest,
    ctx: AuthContext = Depends(require_auth),
) -> SyncPushResponse:
    # TODO: Validate ops and apply to Neon.
    results = [SyncPushResult(op_id=op.op_id, ok=True) for op in body.ops]
    return SyncPushResponse(results=results, cursor=None)


@app.get("/sync/pull", response_model=SyncPullResponse)
def sync_pull(
    cursor: str | None = None,
    ctx: AuthContext = Depends(require_auth),
) -> SyncPullResponse:
    # TODO: Return deltas from Neon scoped by ctx role.
    return SyncPullResponse(cursor=cursor, changes={})
