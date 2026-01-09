from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile_completed: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    role: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("role in ('student', 'lecturer')", name="ck_users_role"),
    )


class Student(Base):
    __tablename__ = "student"

    student_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    matric_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Lecturer(Base):
    __tablename__ = "lecturer"

    lecturer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)


class FaceData(Base):
    __tablename__ = "face_data"

    face_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    face_template: Mapped[str | None] = mapped_column(Text, nullable=True)


class Course(Base):
    __tablename__ = "course"

    course_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_name: Mapped[str] = mapped_column(String(255), nullable=False)
    course_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    lecturer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lecturer.lecturer_id", ondelete="SET NULL"), nullable=True
    )


class Session(Base):
    __tablename__ = "session"

    session_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course.course_id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)


class Attendance(Base):
    __tablename__ = "attendance"

    attendance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("session.session_id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
