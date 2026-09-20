from sqlalchemy import delete, select

from app.models import AuditLog, User
from app.services.audit_logs import AUDIT_OUTCOME_SUCCESS, add_audit_log


def test_audit_log_schema_has_no_freeform_or_file_payload_columns():
    assert set(AuditLog.__table__.columns.keys()) == {
        "id",
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "outcome",
        "reason_code",
        "created_at",
    }


async def test_audit_log_survives_user_deletion_without_personal_payload(profile_context):
    _, db, (user, _) = profile_context
    event = await add_audit_log(
        db,
        actor_user_id=user.id,
        action="delete",
        resource_type="avatar",
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    event_id = event.id
    await db.commit()

    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    db.expire_all()

    retained = await db.scalar(select(AuditLog).where(AuditLog.id == event_id))
    assert retained is not None
    assert retained.actor_user_id is None
    assert retained.resource_id is None
    assert retained.reason_code is None
