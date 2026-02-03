"""add enrollment table

Revision ID: 0004_add_enrollment
Revises: 13e27d19155e
Create Date: 2026-02-03 10:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0004_add_enrollment'
down_revision = '13e27d19155e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enrollment table
    op.create_table('enrollment',
        sa.Column('enrollment_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['student.student_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['course.course_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('enrollment_id'),
        sa.CheckConstraint('student_id IS NOT NULL AND course_id IS NOT NULL')
    )
    
    # Create index for faster lookups
    op.create_index('idx_enrollment_student', 'enrollment', ['student_id'])
    op.create_index('idx_enrollment_course', 'enrollment', ['course_id'])
    
    # Create unique constraint to prevent duplicate enrollments
    op.create_index('idx_enrollment_unique', 'enrollment', ['student_id', 'course_id'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_enrollment_unique', table_name='enrollment')
    op.drop_index('idx_enrollment_course', table_name='enrollment')
    op.drop_index('idx_enrollment_student', table_name='enrollment')
    op.drop_table('enrollment')
