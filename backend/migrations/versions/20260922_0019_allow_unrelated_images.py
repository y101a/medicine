"""Allow encrypted unrelated image attachments.

Revision ID: 20260922_0019
Revises: 20260921_0018
"""

import sqlalchemy as sa
from alembic import op

revision = "20260922_0019"
down_revision = "20260921_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_attachments_image_category_supported"),
        "attachments",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_category_supported"),
        "attachments",
        "image_category IS NULL OR image_category IN "
        "('report', 'medical_imaging', 'body_photo', 'unrelated')",
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM attachments WHERE image_category = 'unrelated'")
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade while unrelated image attachments exist; "
            "delete them through the application first"
        )
    op.drop_constraint(
        op.f("ck_attachments_image_category_supported"),
        "attachments",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_attachments_image_category_supported"),
        "attachments",
        "image_category IS NULL OR image_category IN "
        "('report', 'medical_imaging', 'body_photo')",
    )