"""Audit events participate in the caller's transaction; no implicit commit."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent


async def record_audit(
    session: AsyncSession, *, actor_id: int | None, action: str, target: str, request_id: str
) -> AuditEvent:
    """Add an audit event to the caller-owned transaction; do not commit."""
    event = AuditEvent(actor_id=actor_id, action=action, target=target, request_id=request_id)
    session.add(event)
    await session.flush()
    return event
