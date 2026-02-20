"""add course_id to attendance

Revision ID: 0005_add_course_id
Revises: 0004_add_enrollment
Create Date: 2026-02-20 10:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005_add_course_id'
down_revision = '0004_add_enrollment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add course_id column as nullable first
    op.add_column('attendance', sa.Column('course_id', sa.Integer(), nullable=True))
    
    # Populate course_id from session.course_id for existing records
    op.execute("""
        UPDATE attendance 
        SET course_id = session.course_id
        FROM session
        WHERE attendance.session_id = session.session_id
    """)
    
    # Now make it NOT NULL
    op.alter_column('attendance', 'course_id', nullable=False)
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_attendance_course_id',
        'attendance', 'course',
        ['course_id'], ['course_id'],
        ondelete='CASCADE'
    )
    
    # Create index for faster lookups
    op.create_index('idx_attendance_course', 'attendance', ['course_id'])


def downgrade() -> None:
    op.drop_index('idx_attendance_course', table_name='attendance')
    op.drop_constraint('fk_attendance_course_id', 'attendance', type_='foreignkey')
    op.drop_column('attendance', 'course_id')
