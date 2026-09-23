"""Allow encrypted medication leaflet image attachments.

Revision ID: 20260923_0021
Revises: 20260923_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0021"
down_revision = "20260923_0020"
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
        "('report', 'medical_imaging', 'body_photo', 'medication_leaflet', 'unrelated')",
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM attachments "
            "WHERE image_category = 'medication_leaflet'"
        )
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade while medication leaflet image attachments exist; "
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
        "('report', 'medical_imaging', 'body_photo', 'unrelated')",
    )
