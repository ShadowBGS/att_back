from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import logging
import os
import tempfile
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
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    CourseRequest,
    CourseResponse,
    CourseListItem,
    CourseListResponse,
    SessionCreateRequest,
    SessionResponse,
    StudentSummary,
    StudentEnrollmentInfo,
    StudentSessionInfo,
    AttendanceRow,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncPushResult,
)

settings = get_settings()

# Initialize Firebase Admin SDK
svc_env = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if svc_env:
    path = os.path.join(tempfile.gettempdir(), "firebase.json")
    with open(path, "w") as f:
        f.write(svc_env)
    os.environ["FIREBASE_SERVICE_ACCOUNT_FILE"] = path

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
        # Update name if provided (for email registration)
        if body.name:
            name_val = body.name.strip()
            if name_val:
                user.name = name_val
        user.profile_completed = True
        
        # Create Student or Lecturer record
        from app.models import Student, Lecturer
        
        if user.role == 'student':
            # Check if student record already exists
            existing_student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
            if not existing_student:
                # Check if matric_no is already taken by another user
                matric_conflict = db.query(Student).filter(Student.matric_no == user.external_id).one_or_none()
                if matric_conflict:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Matric number {user.external_id} is already registered to another account."
                    )
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
                # Check if new matric_no conflicts with another student
                if existing_student.matric_no != user.external_id:
                    matric_conflict = db.query(Student).filter(
                        Student.matric_no == user.external_id,
                        Student.user_id != user.id
                    ).one_or_none()
                    if matric_conflict:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Matric number {user.external_id} is already registered to another account."
                        )
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


@app.patch("/profile/update", response_model=ProfileUpdateResponse)
def profile_update(
    body: ProfileUpdateRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    try:
        from app.models import Student, Lecturer

        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if body.name is not None:
            name_val = body.name.strip()
            if name_val:
                user.name = name_val

        if body.external_id is not None:
            external_val = body.external_id.strip()
            if external_val:
                user.external_id = external_val

        if body.department is not None:
            department_val = body.department.strip()
            if department_val:
                user.department = department_val

        if user.role == "student" and user.external_id:
            student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
            if not student:
                student = Student(
                    user_id=user.id,
                    matric_no=user.external_id,
                    department=user.department,
                    level=None,
                )
                db.add(student)
            else:
                student.matric_no = user.external_id
                student.department = user.department

        if user.role == "lecturer":
            lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
            if not lecturer:
                lecturer = Lecturer(user_id=user.id, department=user.department)
                db.add(lecturer)
            else:
                lecturer.department = user.department

        if user.external_id and user.department:
            user.profile_completed = True

        db.commit()
        db.refresh(user)

        return ProfileUpdateResponse(
            firebase_uid=user.firebase_uid,
            email=user.email,
            name=user.name,
            role=user.role,
            external_id=user.external_id,
            department=user.department,
            profile_completed=user.profile_completed,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("Profile update DB error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Profile update failed (database error).") from e
    except Exception as e:
        logger.exception("Profile update error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Profile update failed (server error).") from e


@app.post("/sync/push", response_model=SyncPushResponse)
def sync_push(
    body: SyncPushRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SyncPushResponse:
    """Process sync operations from the mobile app."""
    from app.models import Attendance, Course, Lecturer, Session as DbSession, Student
    
    results = []
    
    for op in body.ops:
        try:
            entity = op.entity
            operation = op.op
            payload = op.payload
            
            # Process based on entity type
            if entity == 'attendance' and operation == 'create':
                # Get student by firebase_uid
                student_firebase_uid = payload.get('student_firebase_uid')
                if not student_firebase_uid:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Missing student_firebase_uid"))
                    continue
                
                user = db.query(User).filter(User.firebase_uid == student_firebase_uid).one_or_none()
                if not user:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Student user not found"))
                    continue
                
                student = db.query(Student).filter(Student.user_id == user.id).one_or_none()
                if not student:
                    # Create student record if it doesn't exist (for students who haven't completed profile)
                    student = Student(
                        user_id=user.id,
                        matric_no=user.external_id or f"TEMP_{user.firebase_uid[:8]}",
                        department=user.department,
                        level=None
                    )
                    db.add(student)
                    db.flush()  # Get the student_id
                    logger.info(f"Auto-created student record for user {user.id}")
                
                # Get session by server_id (which should be the session_id)
                session_server_id = payload.get('session_id')
                if not session_server_id:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Missing session_id"))
                    continue
                
                session = db.query(DbSession).filter(DbSession.session_id == int(session_server_id)).one_or_none()
                if not session:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Session not found"))
                    continue
                
                # Auto-create enrollment if student is not enrolled in the course
                from app.models import Enrollment
                existing_enrollment = db.query(Enrollment).filter(
                    Enrollment.student_id == student.student_id,
                    Enrollment.course_id == session.course_id
                ).one_or_none()
                
                if not existing_enrollment:
                    enrollment = Enrollment(
                        student_id=student.student_id,
                        course_id=session.course_id
                    )
                    db.add(enrollment)
                    db.flush()
                    logger.info(f"Auto-enrolled student {student.student_id} in course {session.course_id}")
                
                # Check if attendance already exists
                existing_attendance = db.query(Attendance).filter(
                    Attendance.session_id == session.session_id,
                    Attendance.student_id == student.student_id
                ).one_or_none()
                
                if existing_attendance:
                    # Update existing attendance
                    existing_attendance.status = payload.get('status', 'present')
                    existing_attendance.verified = payload.get('face_verified', False)
                    timestamp = payload.get('timestamp')
                    if timestamp:
                        existing_attendance.timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    db.commit()
                    results.append(SyncPushResult(op_id=op.op_id, ok=True))
                    logger.info(f"Updated attendance {existing_attendance.attendance_id} for student {student.student_id}")
                else:
                    # Create new attendance record
                    timestamp = payload.get('timestamp')
                    if timestamp:
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    else:
                        timestamp = datetime.now(timezone.utc)
                    
                    attendance = Attendance(
                        session_id=session.session_id,
                        student_id=student.student_id,
                        status=payload.get('status', 'present'),
                        timestamp=timestamp,
                        verified=payload.get('face_verified', False),
                    )
                    db.add(attendance)
                    db.commit()
                    db.refresh(attendance)
                    
                    results.append(SyncPushResult(op_id=op.op_id, ok=True))
                    logger.info(f"Created attendance {attendance.attendance_id} for student {student.student_id} in session {session.session_id}")
            
            elif entity == 'session' and operation == 'create':
                # Get course by server_id
                course_server_id = payload.get('course_id')
                if not course_server_id:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Missing course_id"))
                    continue
                
                course = db.query(Course).filter(Course.course_id == int(course_server_id)).one_or_none()
                if not course:
                    results.append(SyncPushResult(op_id=op.op_id, ok=False, error="Course not found"))
                    continue
                
                # Parse timestamps
                start_time = payload.get('start_time')
                end_time = payload.get('end_time')
                if start_time:
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                else:
                    start_time = datetime.now(timezone.utc)
                
                if end_time:
                    end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                else:
                    end_time = start_time + timedelta(hours=1)
                
                # Create session
                session = DbSession(
                    course_id=course.course_id,
                    start_time=start_time,
                    end_time=end_time,
                    qr_code=payload.get('qr_code'),
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                
                results.append(SyncPushResult(op_id=op.op_id, ok=True))
                logger.info(f"Created session {session.session_id} for course {course.course_id}")
            
            else:
                # Unsupported entity or operation, but don't fail
                results.append(SyncPushResult(op_id=op.op_id, ok=True))
        
        except SQLAlchemyError as e:
            logger.exception(f"Sync push DB error for op {op.op_id}")
            db.rollback()
            results.append(SyncPushResult(op_id=op.op_id, ok=False, error=str(e)))
        except Exception as e:
            logger.exception(f"Sync push error for op {op.op_id}")
            results.append(SyncPushResult(op_id=op.op_id, ok=False, error=str(e)))
    
    return SyncPushResponse(results=results, cursor=None)


@app.post("/courses/create", response_model=CourseResponse)
def create_course(
    body: CourseRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CourseResponse:
    """Create a new course (lecturer only)"""
    try:
        from app.models import Course, Lecturer
        
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can create courses")
        
        # Get lecturer record
        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            raise HTTPException(status_code=404, detail="Lecturer profile not found")
        
        # Check if course code already exists
        existing = db.query(Course).filter(Course.course_code == body.course_code.strip().upper()).one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Course code already exists")
        
        # Create course
        course = Course(
            course_code=body.course_code.strip().upper(),
            course_name=body.course_name.strip(),
            lecturer_id=lecturer.lecturer_id,
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        
        logger.info(f"Created course {course.course_id}: {course.course_code}")
        
        return CourseResponse(
            course_id=course.course_id,
            course_code=course.course_code,
            course_name=course.course_name,
            lecturer_id=course.lecturer_id,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("Create course DB error")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to create course (database error).",
        ) from e
    except Exception as e:
        logger.exception("Create course unexpected error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create course.") from e


@app.patch("/courses/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: int,
    body: CourseRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CourseResponse:
    """Update a course (lecturer only, must be the course owner)"""
    try:
        from app.models import Course, Lecturer
        
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can update courses")
        
        # Get the course
        course = db.query(Course).filter(Course.course_id == course_id).one_or_none()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        
        # Check if user is the lecturer who owns this course
        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=403, detail="You can only update your own courses")
        
        # Check if new course code already exists (and is different from current)
        if body.course_code.strip().upper() != course.course_code:
            existing = db.query(Course).filter(Course.course_code == body.course_code.strip().upper()).one_or_none()
            if existing:
                raise HTTPException(status_code=409, detail="Course code already exists")
        
        # Update course
        course.course_code = body.course_code.strip().upper()
        course.course_name = body.course_name.strip()
        if body.description:
            course.description = body.description.strip()
        
        db.commit()
        db.refresh(course)
        
        logger.info(f"Updated course {course.course_id}: {course.course_code}")
        
        return CourseResponse(
            course_id=course.course_id,
            course_code=course.course_code,
            course_name=course.course_name,
            lecturer_id=course.lecturer_id,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("Update course DB error")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update course (database error).",
        ) from e
    except Exception as e:
        logger.exception("Update course unexpected error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update course.") from e


@app.delete("/courses/{course_id}")
def delete_course(
    course_id: int,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a course (lecturer only, must be the course owner)"""
    try:
        from app.models import Course, Lecturer
        
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can delete courses")
        
        # Get the course
        course = db.query(Course).filter(Course.course_id == course_id).one_or_none()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")
        
        # Check if user is the lecturer who owns this course
        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=403, detail="You can only delete your own courses")
        
        # Delete course
        db.delete(course)
        db.commit()
        
        logger.info(f"Deleted course {course_id}: {course.course_code}")
        
        return {"message": "Course deleted successfully"}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("Delete course DB error")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete course (database error).",
        ) from e
    except Exception as e:
        logger.exception("Delete course unexpected error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete course.") from e


@app.get("/courses/my-courses")
def get_my_courses(
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
)-> CourseListResponse:
    """Get courses for the authenticated user.

    Note: student enrollments are not implemented on the backend yet.
    """
    try:
        from app.models import Course, Lecturer
        
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.role != 'lecturer':
            return CourseListResponse(courses=[])

        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            return CourseListResponse(courses=[])

        courses = db.query(Course).filter(Course.lecturer_id == lecturer.lecturer_id).all()
        return CourseListResponse(
            courses=[
                CourseListItem(
                    course_id=c.course_id,
                    course_code=c.course_code,
                    course_name=c.course_name,
                    lecturer_id=c.lecturer_id,
                )
                for c in courses
            ]
        )
    except Exception as e:
        logger.exception("Get courses error")
        raise HTTPException(status_code=500, detail="Failed to retrieve courses.") from e


@app.get("/courses/{course_id}/sessions", response_model=list[SessionResponse])
def get_course_sessions(
    course_id: int,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    """Get sessions for a course (lecturer only for now)."""
    try:
        from app.models import Course, Lecturer, Session as DbSession

        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can view sessions")

        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            raise HTTPException(status_code=404, detail="Lecturer profile not found")

        course = db.query(Course).filter(Course.course_id == course_id).one_or_none()
        if not course or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=404, detail="Course not found")

        sessions = (
            db.query(DbSession)
            .filter(DbSession.course_id == course_id)
            .order_by(DbSession.start_time.desc())
            .all()
        )

        return [
            SessionResponse(
                session_id=s.session_id,
                course_id=s.course_id,
                start_time=s.start_time.isoformat(),
                end_time=s.end_time.isoformat(),
                qr_code=s.qr_code,
            )
            for s in sessions
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get course sessions error")
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions.") from e


@app.post("/sessions/create", response_model=SessionResponse)
def create_session(
    body: SessionCreateRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Create a new attendance session for a course (lecturer only)."""
    try:
        from app.models import Course, Lecturer, Session as DbSession

        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can start sessions")

        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            raise HTTPException(status_code=404, detail="Lecturer profile not found")

        course = db.query(Course).filter(Course.course_id == body.course_id).one_or_none()
        if not course or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=404, detail="Course not found")

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(hours=1)

        sess = DbSession(course_id=body.course_id, start_time=now, end_time=end_time, qr_code=None)
        db.add(sess)
        db.commit()
        db.refresh(sess)

        return SessionResponse(
            session_id=sess.session_id,
            course_id=sess.course_id,
            start_time=sess.start_time.isoformat(),
            end_time=sess.end_time.isoformat(),
            qr_code=sess.qr_code,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception("Create session DB error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create session (database error).") from e
    except Exception as e:
        logger.exception("Create session error")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create session.") from e


@app.get("/sessions/{session_id}/attendance", response_model=list[AttendanceRow])
def get_session_attendance(
    session_id: int,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[AttendanceRow]:
    """Get attendance records for a session (lecturer only)."""
    try:
        from app.models import Attendance, Course, Lecturer, Session as DbSession, Student

        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can view attendance")

        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            raise HTTPException(status_code=404, detail="Lecturer profile not found")

        sess = db.query(DbSession).filter(DbSession.session_id == session_id).one_or_none()
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")

        course = db.query(Course).filter(Course.course_id == sess.course_id).one_or_none()
        if not course or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=404, detail="Session not found")

        records = db.query(Attendance).filter(Attendance.session_id == session_id).all()

        rows: list[AttendanceRow] = []
        for rec in records:
            student = db.query(Student).filter(Student.student_id == rec.student_id).one_or_none()
            user_row = db.query(User).filter(User.id == student.user_id).one_or_none() if student else None

            rows.append(
                AttendanceRow(
                    attendance_id=rec.attendance_id,
                    session_id=rec.session_id,
                    status=rec.status,
                    timestamp=rec.timestamp.isoformat(),
                    verified=rec.verified,
                    student=StudentSummary(
                        student_id=rec.student_id,
                        firebase_uid=user_row.firebase_uid if user_row else None,
                        name=user_row.name if user_row else None,
                        email=user_row.email if user_row else None,
                        matric_no=student.matric_no if student else None,
                        department=student.department if student else None,
                    ),
                )
            )

        return rows
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get session attendance error")
        raise HTTPException(status_code=500, detail="Failed to retrieve attendance.") from e


@app.get("/courses/{course_id}/students", response_model=list[StudentSummary])
def get_course_students(
    course_id: int,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[StudentSummary]:
    """Return students who have attendance records in this course.

    Since enrollments aren't modeled on the backend yet, we derive the roster from attendance.
    """
    try:
        from app.models import Attendance, Course, Lecturer, Session as DbSession, Student

        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != 'lecturer':
            raise HTTPException(status_code=403, detail="Only lecturers can view students")

        lecturer = db.query(Lecturer).filter(Lecturer.user_id == user.id).one_or_none()
        if not lecturer:
            raise HTTPException(status_code=404, detail="Lecturer profile not found")

        course = db.query(Course).filter(Course.course_id == course_id).one_or_none()
        if not course or course.lecturer_id != lecturer.lecturer_id:
            raise HTTPException(status_code=404, detail="Course not found")

        session_ids = [s.session_id for s in db.query(DbSession).filter(DbSession.course_id == course_id).all()]
        if not session_ids:
            return []

        student_ids = {
            row[0]
            for row in db.query(Attendance.student_id)
            .filter(Attendance.session_id.in_(session_ids))
            .distinct()
            .all()
        }
        if not student_ids:
            return []

        students = db.query(Student).filter(Student.student_id.in_(student_ids)).all()
        result: list[StudentSummary] = []
        for student in students:
            user_row = db.query(User).filter(User.id == student.user_id).one_or_none()
            result.append(
                StudentSummary(
                    student_id=student.student_id,
                    firebase_uid=user_row.firebase_uid if user_row else None,
                    name=user_row.name if user_row else None,
                    email=user_row.email if user_row else None,
                    matric_no=student.matric_no,
                    department=student.department,
                )
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get course students error")
        raise HTTPException(status_code=500, detail="Failed to retrieve students.") from e


@app.get("/student/my-courses", response_model=StudentEnrollmentInfo)
def get_student_courses(
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> StudentEnrollmentInfo:
    """Get all courses a student is enrolled in"""
    try:
        from app.models import Student, Enrollment, Course
        
        # Get current user
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if user.role != 'student':
            raise HTTPException(status_code=403, detail="Only students can access this endpoint")
        
        # Get student record - use .first() to handle duplicate student records gracefully
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Student profile not found")
        
        # Get enrolled courses
        enrollments = db.query(Enrollment).filter(Enrollment.student_id == student.student_id).all()
        course_ids = [e.course_id for e in enrollments]
        courses = db.query(Course).filter(Course.course_id.in_(course_ids)).all() if course_ids else []
        
        from app.schemas import CourseListItem
        enrolled_courses = [
            CourseListItem(
                course_id=c.course_id,
                course_code=c.course_code,
                course_name=c.course_name,
                lecturer_id=c.lecturer_id,
            )
            for c in courses
        ]
        
        return StudentEnrollmentInfo(
            student_id=student.student_id,
            matric_no=student.matric_no,
            enrolled_courses=enrolled_courses,
            total_enrollments=len(enrolled_courses),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get student courses error")
        raise HTTPException(status_code=500, detail="Failed to retrieve student courses.") from e


@app.get("/student/my-sessions", response_model=list[StudentSessionInfo])
def get_student_sessions(
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[StudentSessionInfo]:
    """Get all sessions for courses a student is enrolled in"""
    try:
        from app.models import Student, Enrollment, Course, Session as DbSession, Attendance
        
        logger.info(f"[/student/my-sessions] Starting for user: {ctx.firebase_uid}")
        
        # Get current user
        user = db.query(User).filter(User.firebase_uid == ctx.firebase_uid).one_or_none()
        if not user:
            logger.warning(f"[/student/my-sessions] User not found: {ctx.firebase_uid}")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"[/student/my-sessions] Found user: {user.id}, role: {user.role}")
        
        if user.role != 'student':
            logger.warning(f"[/student/my-sessions] User is not a student: {user.role}")
            raise HTTPException(status_code=403, detail="Only students can access this endpoint")
        
        # Get student record - use .first() to handle duplicate student records gracefully
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if not student:
            logger.warning(f"[/student/my-sessions] No student record found for user: {user.id}")
            raise HTTPException(status_code=404, detail="Student profile not found")
        
        logger.info(f"[/student/my-sessions] Found student: {student.student_id}")
        
        # Get enrolled course IDs
        enrollments = db.query(Enrollment).filter(Enrollment.student_id == student.student_id).all()
        course_ids = [e.course_id for e in enrollments]
        
        logger.info(f"[/student/my-sessions] Found {len(course_ids)} enrolled courses: {course_ids}")
        
        if not course_ids:
            logger.info("[/student/my-sessions] No enrollments, returning empty list")
            return []
        
        # Get all sessions for enrolled courses
        sessions = db.query(DbSession).filter(DbSession.course_id.in_(course_ids)).order_by(DbSession.start_time.desc()).all()
        logger.info(f"[/student/my-sessions] Found {len(sessions)} total sessions for enrolled courses")
        
        result: list[StudentSessionInfo] = []
        for session in sessions:
            # Get course info
            course = db.query(Course).filter(Course.course_id == session.course_id).one_or_none()
            if not course:
                logger.warning(f"[/student/my-sessions] Course not found for session: {session.session_id}")
                continue
            
            # Check attendance status
            attendance = db.query(Attendance).filter(
                Attendance.session_id == session.session_id,
                Attendance.student_id == student.student_id
            ).one_or_none()
            
            logger.info(f"[/student/my-sessions] Session {session.session_id}: course={course.course_code}, attendance={attendance.status if attendance else 'None'}")
            
            result.append(
                StudentSessionInfo(
                    session_id=session.session_id,
                    course_code=course.course_code,
                    course_name=course.course_name,
                    start_time=session.start_time.isoformat(),
                    end_time=session.end_time.isoformat(),
                    attendance_status=attendance.status if attendance else None,
                )
            )
        
        logger.info(f"[/student/my-sessions] Returning {len(result)} sessions")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[/student/my-sessions] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve student sessions: {str(e)}") from e


@app.get("/sync/pull", response_model=SyncPullResponse)
def sync_pull(
    cursor: str | None = None,
    ctx: AuthContext = Depends(require_auth),
) -> SyncPullResponse:
    # TODO: Return deltas from Neon scoped by ctx role.
    return SyncPullResponse(cursor=cursor, changes={})
