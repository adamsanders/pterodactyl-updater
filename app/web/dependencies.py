from typing import Optional
from fastapi import Request

from app.composition import create_status_service
from app.core.protocols import (
    A2SGateway,
    CallTrackerProtocol,
    ConfigRepositoryGateway,
    ConfigRepositoryProtocol,
    CountdownGateway,
    CountdownManagerProtocol,
    PlayerQueryGateway,
    PowerTrackerGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    ServerServiceProtocol,
    StatusAggregationGateway,
    UpdateOrchestratorProtocol,
    WebhookPreviewStoreProtocol,
)
from app.infrastructure import create_a2s_gateway


def get_service(request: Request) -> ServerServiceProtocol:
  return request.app.state.server_service


def get_orchestrator(request: Request) -> UpdateOrchestratorProtocol:
  return request.app.state.orchestrator


def get_repo(request: Request) -> ConfigRepositoryProtocol:
  return request.app.state.repo


def get_ptero(request: Request) -> PterodactylGateway:
  return request.app.state.ptero


def get_countdown(request: Request) -> CountdownManagerProtocol:
  return request.app.state.countdown


def get_preview_store(request: Request) -> WebhookPreviewStoreProtocol:
  return request.app.state.preview_store


def get_a2s(request: Request) -> PlayerQueryGateway:
  if not hasattr(request.app.state, "a2s"):
    tracker = getattr(request.app.state, "call_tracker", None)
    request.app.state.a2s = create_a2s_gateway(call_tracker=tracker)
  return request.app.state.a2s


def get_call_tracker(request: Request) -> CallTrackerProtocol:
  return request.app.state.call_tracker


def get_runtime_state(request: Request) -> Optional[RuntimeStateStoreProtocol]:
  return getattr(request.app.state, "runtime_state", None)


def get_power_tracker(request: Request) -> Optional[PowerTrackerGateway]:
  return getattr(request.app.state, "power_tracker", None)


def get_status_service(request: Request) -> StatusAggregationGateway:
  if not hasattr(request.app.state, "status_service"):
    request.app.state.status_service = create_status_service(
        repository=get_repo(request),
        ptero=get_ptero(request),
        countdown=get_countdown(request),
        preview_store=get_preview_store(request),
        orchestrator=get_orchestrator(request),
        a2s=get_a2s(request),
        call_tracker=getattr(request.app.state, "call_tracker", None),
        runtime_state=get_runtime_state(request),
        power_tracker=get_power_tracker(request),
    )
  return request.app.state.status_service


__all__ = [
    "get_service",
    "get_orchestrator",
    "get_repo",
    "get_ptero",
    "get_countdown",
    "get_preview_store",
    "get_a2s",
    "get_call_tracker",
    "get_runtime_state",
    "get_power_tracker",
    "get_status_service",
]
