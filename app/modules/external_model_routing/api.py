from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.core.auth.dependencies import set_dashboard_error_format, validate_dashboard_session
from app.dependencies import ExternalModelRoutingContext, get_external_model_routing_context
from app.modules.external_model_routing.schemas import (
    ExternalModelRouteCreateRequest,
    ExternalModelRouteResponse,
    ExternalModelRouteUpdateRequest,
    ExternalModelRoutingAdminResponse,
    ExternalProviderCreateRequest,
    ExternalProviderResponse,
    ExternalProviderUpdateRequest,
)

router = APIRouter(
    prefix="/api/settings/external-model-routing",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("", response_model=ExternalModelRoutingAdminResponse)
async def get_external_model_routing_admin(
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> ExternalModelRoutingAdminResponse:
    return await context.service.get_admin()


@router.post("/providers", response_model=ExternalProviderResponse)
async def create_external_provider(
    payload: ExternalProviderCreateRequest,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> ExternalProviderResponse:
    return await context.service.create_provider(payload)


@router.put("/providers/{provider_id}", response_model=ExternalProviderResponse)
async def update_external_provider(
    provider_id: str,
    payload: ExternalProviderUpdateRequest,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> ExternalProviderResponse:
    return await context.service.update_provider(provider_id, payload)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_external_provider(
    provider_id: str,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> Response:
    await context.service.delete_provider(provider_id)
    return Response(status_code=204)


@router.post("/routes", response_model=ExternalModelRouteResponse)
async def create_external_model_route(
    payload: ExternalModelRouteCreateRequest,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> ExternalModelRouteResponse:
    return await context.service.create_route(payload)


@router.put("/routes/{public_model:path}", response_model=ExternalModelRouteResponse)
async def update_external_model_route(
    public_model: str,
    payload: ExternalModelRouteUpdateRequest,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> ExternalModelRouteResponse:
    return await context.service.update_route(public_model, payload)


@router.delete("/routes/{public_model:path}", status_code=204)
async def delete_external_model_route(
    public_model: str,
    context: ExternalModelRoutingContext = Depends(get_external_model_routing_context),
) -> Response:
    await context.service.delete_route(public_model)
    return Response(status_code=204)
