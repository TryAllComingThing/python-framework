"""IAM HTTP adapters: V1 is a stable array, V2 is a stable page."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.openapi import error_responses
from app.common.pagination import Page, PageParams
from app.common.responses import ApiResponse, success
from app.core.database import get_session
from app.modules.auth.dependencies import Identity, get_identity, permission
from app.modules.iam.menu import visible_menus
from app.modules.iam.query import list_user_summaries, page_user_summaries
from app.modules.iam.schemas import MenuResponse, UserSummaryResponse

router = APIRouter(prefix="/api/v1/iam", tags=["iam"])
v2_router = APIRouter(prefix="/api/v2/iam", tags=["iam"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
IdentityDep = Annotated[Identity, Depends(get_identity)]
UserListIdentityDep = Annotated[Identity, Depends(permission("system:user:list"))]
PageDep = Annotated[PageParams, Depends()]


def mark_legacy(response: Response) -> None:
    """Advertise the capped legacy representation without changing its JSON shape."""
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v2/iam/users>; rel="successor-version"'
    response.headers["Warning"] = '299 - "Legacy response returns at most 100 users"'


async def _list_users(
    request: Request,
    response: Response,
    identity: Identity,
    db: AsyncSession,
) -> ApiResponse[list[UserSummaryResponse]]:
    mark_legacy(response)
    users = await list_user_summaries(db, identity.principal)
    return success(users, request.state.request_id)


@router.get(
    "/users",
    response_model=ApiResponse[list[UserSummaryResponse]],
    deprecated=True,
    operation_id="iam_v1_users_list",
    responses=error_responses(401, 403, 500, 503),
)
async def list_users(
    request: Request,
    response: Response,
    identity: UserListIdentityDep,
    db: SessionDep,
) -> ApiResponse[list[UserSummaryResponse]]:
    """V1 fixed-shape legacy array; never negotiate a second schema at this URL."""
    return await _list_users(request, response, identity, db)


@router.get(
    "/users/legacy",
    response_model=ApiResponse[list[UserSummaryResponse]],
    deprecated=True,
    operation_id="iam_v1_users_legacy_list",
    responses=error_responses(401, 403, 500, 503),
)
async def list_users_legacy(
    request: Request,
    response: Response,
    identity: UserListIdentityDep,
    db: SessionDep,
) -> ApiResponse[list[UserSummaryResponse]]:
    """Compatibility alias with the same contract as the canonical V1 route."""
    return await _list_users(request, response, identity, db)


@router.get(
    "/menus",
    response_model=ApiResponse[list[MenuResponse]],
    operation_id="iam_menus_list",
    responses=error_responses(401, 500, 503),
)
async def list_menus(
    request: Request,
    identity: IdentityDep,
    db: SessionDep,
) -> ApiResponse[list[MenuResponse]]:
    menus = await visible_menus(db, identity.principal.permissions)
    return success(menus, request.state.request_id)


@v2_router.get(
    "/users",
    response_model=ApiResponse[Page[UserSummaryResponse]],
    operation_id="iam_v2_users_page",
    responses=error_responses(401, 403, 422, 500, 503),
)
async def list_users_v2(
    request: Request,
    identity: UserListIdentityDep,
    db: SessionDep,
    page: PageDep,
) -> ApiResponse[Page[UserSummaryResponse]]:
    result = await page_user_summaries(db, identity.principal, page)
    return success(result, request.state.request_id)
