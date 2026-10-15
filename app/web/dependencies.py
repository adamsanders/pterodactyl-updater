from typing import Optional
from fastapi import Request

from app.adapters.a2s import A2SAdapter
from app.core.protocols import (
    A2SGateway,
    CallTrackerProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
)
from app.services.preview_store import WebhookPreviewStore
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.services.updater import UpdateOrchestrator
from app.web.filters import discord_markdown


def get_service(request: Request) -> ServerService:
  return request.app.state.server_service


def get_orchestrator(request: Request) -> UpdateOrchestrator:
  return request.app.state.orchestrator


def get_repo(request: Request) -> ConfigRepositoryProtocol:
  return request.app.state.repo


def get_ptero(request: Request) -> PterodactylGateway:
  return request.app.state.ptero


def get_countdown(request: Request) -> CountdownManagerProtocol:
  return request.app.state.countdown


def get_preview_store(request: Request) -> WebhookPreviewStore:
  return request.app.state.preview_store


def get_a2s(request: Request) -> A2SGateway:
  if not hasattr(request.app.state, "a2s"):
    request.app.state.a2s = A2SAdapter()
  return request.app.state.a2s


def get_call_tracker(request: Request) -> CallTrackerProtocol:
  return request.app.state.call_tracker


def get_runtime_state(request: Request) -> Optional[RuntimeStateStoreProtocol]:
  return getattr(request.app.state, "runtime_state", None)


def get_status_service(request: Request) -> StatusAggregationService:
  if not hasattr(request.app.state, "status_service"):
    request.app.state.status_service = StatusAggregationService(
        repository=get_repo(request),
        ptero=get_ptero(request),
        countdown=get_countdown(request),
        preview_store=get_preview_store(request),
        orchestrator=get_orchestrator(request),
        a2s=get_a2s(request),
        call_tracker=getattr(request.app.state, "call_tracker", None),
        markdown_formatter=discord_markdown,
        runtime_state=get_runtime_state(request),
    )
  return request.app.state.status_service
