"""Scopes: written authorisation for active operations."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from omniosint.api.deps import ContextDep, RequestInfoDep, SessionDep, permission_doc, require
from omniosint.api.schemas.common import ERROR_RESPONSES
from omniosint.api.schemas.intel import (
    RevokeIn,
    ScopeCheckIn,
    ScopeDecisionOut,
    ScopeDetailOut,
    ScopeIn,
    ScopeList,
    ScopeOut,
    ScopeRuleIn,
    ScopeRuleOut,
)
from omniosint.audit.service import record
from omniosint.auth.permissions import Permission
from omniosint.auth.service import Principal
from omniosint.collection.inputs import resolve
from omniosint.core.timeutil import utcnow
from omniosint.database.models import Scope
from omniosint.providers.base import Operation
from omniosint.scopes import service as scopes
from omniosint.scopes.manager import evaluate
from omniosint.scopes.rules import target_for

router = APIRouter(prefix="/scopes", tags=["scopes"])

CanRead = Annotated[Principal, Depends(require(Permission.SCOPES_READ))]
CanManage = Annotated[Principal, Depends(require(Permission.SCOPES_MANAGE))]
_ERRORS: dict[int | str, dict[str, Any]] = {401: ERROR_RESPONSES[401], 403: ERROR_RESPONSES[403]}
_CHANGE: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    404: ERROR_RESPONSES[404],
    409: ERROR_RESPONSES[409],
    422: ERROR_RESPONSES[422],
}


def _out(scope: Scope) -> ScopeOut:
    data = {
        column: getattr(scope, column) for column in ScopeOut.model_fields if column != "status"
    }
    return ScopeOut(**data, status=scopes.scope_status(scope))


def _rule(item: ScopeRuleIn) -> scopes.RuleInput:
    return scopes.RuleInput(
        kind=item.kind,
        value=item.value,
        is_exclusion=item.is_exclusion,
        ports=tuple(item.ports) if item.ports is not None else None,
    )


@router.get(
    "",
    response_model=ScopeList,
    summary="List scopes",
    openapi_extra=permission_doc(Permission.SCOPES_READ),
    responses=_ERRORS,
)
async def list_scopes(_principal: CanRead, session: SessionDep) -> ScopeList:
    return ScopeList(items=[_out(scope) for scope in await scopes.list_scopes(session)])


@router.post(
    "",
    response_model=ScopeDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a scope of written authorisation",
    description=(
        "Creating a scope states that written authorisation exists for every target "
        "it lists (`authorization_confirmed` must be true). It is recorded in the audit trail."
    ),
    openapi_extra=permission_doc(Permission.SCOPES_MANAGE),
    responses=_CHANGE,
)
async def create_scope(
    body: ScopeIn, principal: CanManage, session: SessionDep, info: RequestInfoDep
) -> ScopeDetailOut:
    scope = await scopes.create_scope(
        session,
        scopes.ScopeInput(
            name=body.name,
            mode=body.mode,
            authorized_by=body.authorized_by,
            valid_until=body.valid_until,
            authorization_confirmed=body.authorization_confirmed,
            valid_from=body.valid_from,
            description=body.description,
            authorization_reference=body.authorization_reference,
            authorization_note=body.authorization_note,
            rules=tuple(_rule(item) for item in body.rules),
        ),
        actor=principal.actor,
        request=info,
    )
    return await _detail(session, scope.id)


async def _detail(session: Any, scope_id: uuid.UUID) -> ScopeDetailOut:
    scope, rules = await scopes.get_scope(session, scope_id)
    return ScopeDetailOut(
        scope=_out(scope), rules=[ScopeRuleOut.model_validate(rule) for rule in rules]
    )


@router.get(
    "/{scope_id}",
    response_model=ScopeDetailOut,
    summary="Get a scope and its rules",
    openapi_extra=permission_doc(Permission.SCOPES_READ),
    responses={**_ERRORS, 404: ERROR_RESPONSES[404]},
)
async def get_scope(
    scope_id: uuid.UUID, _principal: CanRead, session: SessionDep
) -> ScopeDetailOut:
    return await _detail(session, scope_id)


@router.post(
    "/{scope_id}/rules",
    response_model=ScopeDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a target or an exclusion",
    openapi_extra=permission_doc(Permission.SCOPES_MANAGE),
    responses=_CHANGE,
)
async def add_rule(
    scope_id: uuid.UUID,
    body: ScopeRuleIn,
    principal: CanManage,
    session: SessionDep,
    info: RequestInfoDep,
) -> ScopeDetailOut:
    await scopes.add_rule(session, scope_id, _rule(body), actor=principal.actor, request=info)
    return await _detail(session, scope_id)


@router.delete(
    "/{scope_id}/rules/{rule_id}",
    response_model=ScopeDetailOut,
    summary="Remove a rule",
    openapi_extra=permission_doc(Permission.SCOPES_MANAGE),
    responses=_CHANGE,
)
async def remove_rule(
    scope_id: uuid.UUID,
    rule_id: uuid.UUID,
    principal: CanManage,
    session: SessionDep,
    info: RequestInfoDep,
) -> ScopeDetailOut:
    await scopes.remove_rule(session, scope_id, rule_id, actor=principal.actor, request=info)
    return await _detail(session, scope_id)


@router.post(
    "/{scope_id}/revoke",
    response_model=ScopeDetailOut,
    summary="Revoke a scope",
    description=(
        "Scopes are never deleted, so the authority behind past operations stays on record."
    ),
    openapi_extra=permission_doc(Permission.SCOPES_MANAGE),
    responses=_CHANGE,
)
async def revoke_scope(
    scope_id: uuid.UUID,
    body: RevokeIn,
    principal: CanManage,
    session: SessionDep,
    info: RequestInfoDep,
) -> ScopeDetailOut:
    await scopes.revoke_scope(session, scope_id, body.reason, actor=principal.actor, request=info)
    return await _detail(session, scope_id)


@router.post(
    "/{scope_id}/check",
    response_model=ScopeDecisionOut,
    summary="Check whether a target is in scope",
    description="Answers what the scope manager would decide now. Nothing is run.",
    openapi_extra=permission_doc(Permission.SCOPES_READ),
    responses={**_ERRORS, 404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422]},
)
async def check(
    scope_id: uuid.UUID,
    body: ScopeCheckIn,
    principal: CanRead,
    context: ContextDep,
    session: SessionDep,
    info: RequestInfoDep,
) -> ScopeDecisionOut:
    view = await scopes.load_view(session, scope_id)
    indicator, _result = resolve(
        body.input, body.type, default_region=context.settings.collection.default_phone_region
    )
    target = target_for(indicator.type, indicator.value)
    decision = evaluate(Operation(body.operation), target, view, now=utcnow(), ports=body.ports)
    record(
        session,
        action="scope.checked",
        actor=principal.actor,
        outcome="success" if decision.allowed else "denied",
        target_type="scope",
        target_id=scope_id,
        request=info,
        details={"when": "manual_check", **decision.as_dict(), "target": indicator.value},
    )
    await session.commit()
    return ScopeDecisionOut(**decision.as_dict(), target=target.describe() if target else None)
