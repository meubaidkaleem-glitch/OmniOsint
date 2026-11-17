"""Dashboard.

Every number comes from a database record. A metric whose module has not been
built is returned as unavailable with the phase that delivers it; it is never
reported as zero.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from omniosint.api.deps import ActivePrincipalDep, ContextDep, SessionDep
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.system import (
    ActivityItem,
    DashboardComponent,
    DashboardHealth,
    DashboardResponse,
    FeatureCounts,
    Metric,
    ProviderCounts,
)
from omniosint.audit import service as audit
from omniosint.auth.permissions import Permission
from omniosint.core.features import PHASES, PLANNED_DASHBOARD_METRICS, feature_counts
from omniosint.core.timeutil import utcnow
from omniosint.database.models import AuditEvent, User, UserSession
from omniosint.providers.catalog import load_catalogue
from omniosint.system.health import collect_health

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_ACTIVITY_LIMIT = 12


def _available(key: str, label: str, value: int) -> Metric:
    return Metric(
        key=key, label=label, available=True, value=value, planned_phase=None, phase_title=None
    )


@router.get(
    "",
    response_model=DashboardResponse,
    summary="Dashboard data",
    responses={401: ERROR_RESPONSES[401]},
)
async def dashboard(
    principal: ActivePrincipalDep, context: ContextDep, session: SessionDep
) -> DashboardResponse:
    now = utcnow()
    can_read_system = principal.has(Permission.SYSTEM_READ.value)
    can_read_audit = principal.has(Permission.AUDIT_READ.value)
    can_read_users = principal.has(Permission.USERS_READ.value)

    report = await collect_health(context.db, context.settings, context.paths)

    metrics: list[Metric] = []
    own_sessions = (
        await session.execute(
            select(func.count())
            .select_from(UserSession)
            .where(
                UserSession.user_id == principal.user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )
    ).scalar_one()
    metrics.append(_available("my_active_sessions", "Your active sessions", int(own_sessions)))

    if can_read_users:
        active_users = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.deleted_at.is_(None), User.is_active.is_(True))
            )
        ).scalar_one()
        metrics.append(_available("users_active", "Active user accounts", int(active_users)))

    if can_read_audit:
        since = now - timedelta(hours=24)
        sign_ins = (
            await session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "auth.login.success", AuditEvent.occurred_at >= since)
            )
        ).scalar_one()
        failures = (
            await session.execute(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "auth.login.failure", AuditEvent.occurred_at >= since)
            )
        ).scalar_one()
        metrics.append(_available("sign_ins_24h", "Sign-ins, last 24 hours", int(sign_ins)))
        metrics.append(
            _available("failed_sign_ins_24h", "Failed sign-ins, last 24 hours", int(failures))
        )

    metrics.extend(
        Metric(
            key=planned.key,
            label=planned.label,
            available=False,
            value=None,
            planned_phase=planned.phase,
            phase_title=PHASES[planned.phase],
        )
        for planned in PLANNED_DASHBOARD_METRICS
    )

    activity_page = await audit.list_events(
        session,
        limit=_ACTIVITY_LIMIT,
        actor_user_id=None if can_read_audit else principal.user_id,
    )

    catalogue = load_catalogue()
    provider_counts = catalogue.status_counts()

    return DashboardResponse(
        generated_at=now,
        health=DashboardHealth(
            status=report.status.value,
            checked_at=report.checked_at,
            components=[
                DashboardComponent(
                    name=item.name,
                    label=item.label,
                    status=item.status.value,
                    required=item.required,
                    detail=item.detail if can_read_system else None,
                )
                for item in report.components
            ],
        ),
        metrics=metrics,
        modules=FeatureCounts(**feature_counts()),
        providers=ProviderCounts(total=len(catalogue.providers), **provider_counts),
        recent_activity=[
            ActivityItem(
                id=event.id,
                occurred_at=event.occurred_at,
                action=event.action,
                outcome=event.outcome,
                actor_label=event.actor_label,
                target_type=event.target_type,
                target_id=event.target_id,
            )
            for event in activity_page.items
        ],
        activity_scope="all" if can_read_audit else "own",
    )
