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


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    external_id: str | None = None
    department: str | None = None


class ProfileUpdateResponse(BaseModel):
    firebase_uid: str
    email: str | None = None
    name: str | None = None
    role: str
    external_id: str | None = None
    department: str | None = None
    profile_completed: bool


class CourseRequest(BaseModel):
    course_code: str
    course_name: str
    description: str | None = None


class CourseResponse(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    description: str | None = None
    lecturer_id: int | None = None


class CourseListItem(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    lecturer_id: int | None = None


class CourseListResponse(BaseModel):
    courses: list[CourseListItem]


class SessionCreateRequest(BaseModel):
    course_id: int


class SessionResponse(BaseModel):
    session_id: int
    course_id: int
    start_time: str
    end_time: str
    qr_code: str | None = None


class StudentSummary(BaseModel):
    student_id: int
    firebase_uid: str | None = None
    name: str | None = None
    email: str | None = None
    matric_no: str | None = None
    department: str | None = None


class AttendanceRow(BaseModel):
    attendance_id: int
    session_id: int
    status: str | None = None
    timestamp: str
    verified: bool
    student: StudentSummary


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


class StudentEnrollmentInfo(BaseModel):
    """Information about a student's enrollments"""
    student_id: int
    matric_no: str
    enrolled_courses: list[CourseListItem]
    total_enrollments: int


class StudentSessionInfo(BaseModel):
    """Information about sessions for a student"""
    session_id: int
    course_code: str
    course_name: str
    start_time: str
    end_time: str
    attendance_status: str | None = None

