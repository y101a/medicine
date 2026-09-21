"""Relax attachment limits: 30 MB per file, 100 pages, 5 attachments per message.

按用户 2026-09-21 确认的方案 B 放宽上传限制。模型侧上下文预算
（`ATTACHMENT_CONTEXT_MAX_CHARS`，12000 字符）**没有变**，所以这里只改「收得下」的边界：
单文件体积、PDF/PPTX 页数、每条消息可引用的附件数。

这三个 CHECK 约束是 20260921_0016 建表时写进去的，只改 Pydantic/ORM 声明不够——
数据库会直接拒绝插入（实测：position=3 触发
`ck_message_attachments_position_supported` 违反）。所以表约束与 ORM 声明必须同时改。
"""

from alembic import op

revision = "20260921_0017"
down_revision = "20260921_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_attachments_byte_size_supported"), "attachments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_attachments_byte_size_supported"),
        "attachments",
        "byte_size BETWEEN 1 AND 31457280",
    )
    op.drop_constraint(
        op.f("ck_attachments_page_count_supported"), "attachments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_attachments_page_count_supported"),
        "attachments",
        "page_count IS NULL OR page_count BETWEEN 1 AND 100",
    )
    op.drop_constraint(
        op.f("ck_message_attachments_position_supported"),
        "message_attachments",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_message_attachments_position_supported"),
        "message_attachments",
        "position BETWEEN 0 AND 4",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_message_attachments_position_supported"),
        "message_attachments",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_message_attachments_position_supported"),
        "message_attachments",
        "position BETWEEN 0 AND 2",
    )
    op.drop_constraint(
        op.f("ck_attachments_page_count_supported"), "attachments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_attachments_page_count_supported"),
        "attachments",
        "page_count IS NULL OR page_count BETWEEN 1 AND 30",
    )
    op.drop_constraint(
        op.f("ck_attachments_byte_size_supported"), "attachments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_attachments_byte_size_supported"),
        "attachments",
        "byte_size BETWEEN 1 AND 10485760",
    )