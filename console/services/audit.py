"""审计事件写入。由 spark_console.services.audits 迁移为异步。"""

from __future__ import annotations

from db.console_models import AuditEvent


class AuditService:
    async def write(
        self,
        actor_user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        await AuditEvent.create(
            actor_user_id=actor_user_id,
            action=action[:64],
            resource_type=resource_type[:32],
            resource_id=resource_id,
            detail=detail[:240] if detail else None,
        )
