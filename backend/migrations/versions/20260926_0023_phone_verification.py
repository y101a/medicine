"""Add phone verification challenges and auth versioning.

Revision ID: 20260926_0023
Revises: 20260924_0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260926_0023"
down_revision = "20260924_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_users_auth_version_positive"),
        "users",
        "auth_version >= 1",
    )
    op.create_table(
        "phone_verification_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("provider_reference", sa.String(length=128), nullable=True),
        sa.Column("request_ip_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "is_decoy",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "verification_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('registration', 'password_reset', 'phone_binding')",
            name=op.f("ck_phone_verification_challenges_purpose_supported"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_phone_verification_challenges_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name=op.f("ck_phone_verification_challenges_max_attempts_positive"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_phone_verification_challenges_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "resend_available_at > created_at",
            name=op.f("ck_phone_verification_challenges_resend_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_phone_verification_challenges_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_phone_verification_challenges"),
        ),
    )
    op.create_index(
        "ix_phone_verification_phone_purpose_created",
        "phone_verification_challenges",
        ["phone_fingerprint", "purpose", "created_at"],
    )
    op.create_index(
        "ix_phone_verification_ip_created",
        "phone_verification_challenges",
        ["request_ip_fingerprint", "created_at"],
    )
    op.create_index(
        "ix_phone_verification_expiry",
        "phone_verification_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM phone_verification_challenges")
    )
    if count:
        raise RuntimeError(
            "Cannot downgrade while phone verification challenges exist"
        )
    op.drop_index(
        "ix_phone_verification_expiry",
        table_name="phone_verification_challenges",
    )
    op.drop_index(
        "ix_phone_verification_ip_created",
        table_name="phone_verification_challenges",
    )
    op.drop_index(
        "ix_phone_verification_phone_purpose_created",
        table_name="phone_verification_challenges",
    )
    op.drop_table("phone_verification_challenges")
    op.drop_constraint(
        op.f("ck_users_auth_version_positive"),
        "users",
        type_="check",
    )
    op.drop_column("users", "auth_version")
    op.drop_column("users", "phone_verified_at")
