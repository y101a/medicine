from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

AUDIT_OUTCOME_SUCCESS = "success"
AUDIT_OUTCOME_REJECTED = "rejected"


async def add_audit_log(
    db: AsyncSession,
    *,
    actor_user_id: UUID,
    action: str,
    resource_type: str,
    outcome: str,
    resource_id: UUID | None = None,
    reason_code: str | None = None,
) -> AuditLog:
    if not action or len(action) > 64:
        raise ValueError("审计动作必须为 1-64 个字符")
    if not resource_type or len(resource_type) > 64:
        raise ValueError("审计资源类型必须为 1-64 个字符")
    if outcome not in {AUDIT_OUTCOME_SUCCESS, AUDIT_OUTCOME_REJECTED}:
        raise ValueError("审计结果不受支持")
    if reason_code is not None and len(reason_code) > 64:
        raise ValueError("审计原因码不能超过 64 个字符")

    event = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        reason_code=reason_code,
    )
    db.add(event)
    await db.flush()
    return event
