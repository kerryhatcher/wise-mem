"""add projects and memory-project links

Revision ID: 86c8504cd071
Revises: 1e0a06814aae
Create Date: 2026-06-29 19:29:37.841043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86c8504cd071'
down_revision: Union[str, Sequence[str], None] = '1e0a06814aae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Sticky flag: set True when a project this memory was linked to is deleted.
    op.add_column(
        "memory",
        sa.Column(
            "had_deleted_project",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Projects: UUID primary key is the key memories are tied to.
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Many-to-many link; both FKs cascade so deleting either side drops the row.
    op.create_table(
        "memory_project",
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id", "project_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("memory_project")
    op.drop_table("project")
    op.drop_column("memory", "had_deleted_project")
