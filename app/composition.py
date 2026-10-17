import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Optional

from fastapi import FastAPI
import httpx

from app.adapters.vcs import resolve_commit_code
from app.core.config import get_commit_code
from app.core.models import AppConfigModel
from app.core.protocols import (
    BuildSimulatorProtocol,
    CallTrackerProtocol,
    ConfigRepositoryGateway,
    CountdownGateway,
    NotificationGateway,
    PlayerQueryGateway,
    PowerTrackerGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    ServerServiceProtocol,
    StatusAggregationGateway,
    SteamGateway,
    UpdateOrchestratorProtocol,
    WebhookPreviewStoreProtocol,
)
from app.infrastructure import (
    close_resources,
    create_a2s_gateway,
    create_call_tracker,
    create_config_repository,
    create_countdown_manager,
    create_discord_gateway,
    create_power_tracker,
    create_preview_store,
    create_pterodactyl_gateway,
    create_runtime_state_store,
    create_simulated_steam_gateway,
    create_simulator_store,
    create_steam_gateway,
)
from app.services.announcement_service import AnnouncementService
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.services.updater import UpdateOrchestrator

logger = logging.getLogger("updater.composition")


@dataclass
class ApplicationContainer:
  """Strongly-typed composition root container holding all domain gateways, stores, and services."""

  repo: ConfigRepositoryGateway
  runtime_state: RuntimeStateStoreProtocol
  power_tracker: PowerTrackerGateway
  call_tracker: CallTrackerProtocol
  ptero: PterodactylGateway
  real_steam: SteamGateway
  steam: SteamGateway
  discord: NotificationGateway
  a2s: PlayerQueryGateway
  countdown: CountdownGateway
  preview_store: WebhookPreviewStoreProtocol
  simulator_store: BuildSimulatorProtocol
  announcements: AnnouncementService
  orchestrator: UpdateOrchestrator
  server_service: ServerService
  status_service: StatusAggregationService
  commit_code: str
  http_client: Optional[httpx.AsyncClient] = None

  @property
  def server_config_service(self) -> Any:
    return getattr(self.server_service, "config_service", None)

  @property
  def server_power_service(self) -> Any:
    return getattr(self.server_service, "power_service", None)

  @property
  def inspection_service(self) -> Any:
    return getattr(self.orchestrator, "inspection_service", None)

  @property
  def countdown_coordinator(self) -> Any:
    return getattr(self.orchestrator, "countdown_coordinator", None)


def create_status_service(
    repository: ConfigRepositoryGateway,
    ptero: PterodactylGateway,
    countdown: CountdownGateway,
    preview_store: WebhookPreviewStoreProtocol,
    orchestrator: Optional[Any] = None,
    a2s: Optional[PlayerQueryGateway] = None,
    call_tracker: Optional[CallTrackerProtocol] = None,
    runtime_state: Optional[RuntimeStateStoreProtocol] = None,
    power_tracker: Optional[PowerTrackerGateway] = None,
    commit_code: Optional[str] = None,
) -> StatusAggregationService:
  """Factory to instantiate StatusAggregationService adhering to StatusAggregationGateway."""
  return StatusAggregationService(
      repository=repository,
      ptero=ptero,
      countdown=countdown,
      preview_store=preview_store,
      orchestrator=orchestrator,
      a2s=a2s,
      call_tracker=call_tracker,
      runtime_state=runtime_state,
      power_tracker=power_tracker,
      commit_code=commit_code or get_commit_code(),
  )


def create_server_service(
    repository: ConfigRepositoryGateway,
    ptero: PterodactylGateway,
    steam: SteamGateway,
    simulator_store: BuildSimulatorProtocol,
    countdown: CountdownGateway,
    announcements: Optional[AnnouncementService] = None,
    discord: Optional[NotificationGateway] = None,
    preview_store: Optional[WebhookPreviewStoreProtocol] = None,
    runtime_state: Optional[RuntimeStateStoreProtocol] = None,
    orchestrator: Optional[UpdateOrchestratorProtocol] = None,
) -> ServerService:
  """Factory to instantiate ServerService adhering to ServerServiceProtocol."""
  return ServerService(
      repository=repository,
      ptero=ptero,
      steam=steam,
      simulator_store=simulator_store,
      countdown=countdown,
      announcements=announcements,
      discord=discord,
      preview_store=preview_store,
      runtime_state=runtime_state,
      orchestrator=orchestrator,
  )


def create_announcement_service(
    repository: ConfigRepositoryGateway,
    ptero: PterodactylGateway,
    steam: SteamGateway,
    discord: Optional[NotificationGateway] = None,
    preview_store: Optional[WebhookPreviewStoreProtocol] = None,
) -> AnnouncementService:
  """Factory to instantiate AnnouncementService."""
  return AnnouncementService(
      repository=repository,
      ptero=ptero,
      steam=steam,
      discord=discord,
      preview_store=preview_store,
  )


def create_update_orchestrator(
    repository: ConfigRepositoryGateway,
    ptero: PterodactylGateway,
    steam: SteamGateway,
    countdown: CountdownGateway,
    announcements: AnnouncementService,
    simulator_store: BuildSimulatorProtocol,
    runtime_state: RuntimeStateStoreProtocol,
) -> UpdateOrchestrator:
  """Factory to instantiate UpdateOrchestrator adhering to UpdateOrchestratorProtocol."""
  return UpdateOrchestrator(
      repository=repository,
      ptero=ptero,
      steam=steam,
      countdown=countdown,
      announcements=announcements,
      simulator_store=simulator_store,
      runtime_state=runtime_state,
  )


def build_container(
    cfg: Optional[AppConfigModel] = None,
    repo: Optional[ConfigRepositoryGateway] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    call_tracker: Optional[CallTrackerProtocol] = None,
    runtime_state: Optional[RuntimeStateStoreProtocol] = None,
    power_tracker: Optional[PowerTrackerGateway] = None,
    ptero: Optional[PterodactylGateway] = None,
    real_steam: Optional[SteamGateway] = None,
    steam: Optional[SteamGateway] = None,
    discord: Optional[NotificationGateway] = None,
    a2s: Optional[PlayerQueryGateway] = None,
    countdown: Optional[CountdownGateway] = None,
    preview_store: Optional[WebhookPreviewStoreProtocol] = None,
    simulator_store: Optional[BuildSimulatorProtocol] = None,
    announcements: Optional[AnnouncementService] = None,
    orchestrator: Optional[UpdateOrchestrator] = None,
    server_service: Optional[ServerService] = None,
    status_service: Optional[StatusAggregationService] = None,
    commit_code: Optional[str] = None,
) -> ApplicationContainer:
  """Composition root constructing and wiring all application components adhering to domain protocols."""
  call_tracker = call_tracker or create_call_tracker()
  repo = repo or create_config_repository()
  if cfg is None:
    cfg = repo.load()

  if runtime_state is None:
    runtime_state = create_runtime_state_store(cfg)
  else:
    runtime_state.seed_from_config(cfg)

  power_tracker = power_tracker or create_power_tracker()

  if http_client is not None:
    ptero = ptero or create_pterodactyl_gateway(http_client, tracker=power_tracker)
    real_steam = real_steam or create_steam_gateway(http_client)
    discord = discord or create_discord_gateway(http_client)

  a2s = a2s or create_a2s_gateway(call_tracker=call_tracker)
  countdown = countdown or create_countdown_manager()
  preview_store = preview_store or create_preview_store()
  simulator_store = simulator_store or create_simulator_store()

  if steam is None and real_steam is not None:
    steam = create_simulated_steam_gateway(
        real_steam=real_steam,
        simulator_store=simulator_store,
        repository=repo,
    )

  if announcements is None:
    announcements = create_announcement_service(
        repository=repo,
        ptero=ptero,
        steam=steam,
        discord=discord,
        preview_store=preview_store,
    )

  if orchestrator is None:
    orchestrator = create_update_orchestrator(
        repository=repo,
        ptero=ptero,
        steam=steam,
        countdown=countdown,
        announcements=announcements,
        simulator_store=simulator_store,
        runtime_state=runtime_state,
    )

  if server_service is None:
    server_service = create_server_service(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=simulator_store,
        countdown=countdown,
        announcements=announcements,
        runtime_state=runtime_state,
        orchestrator=orchestrator,
    )

  commit_code = commit_code or resolve_commit_code()

  try:
    from app.web.templating import templates

    templates.env.globals["commit_code"] = commit_code
  except Exception as e:
    logger.debug("Templates not initialized: %s", e)

  if status_service is None:
    status_service = create_status_service(
        repository=repo,
        ptero=ptero,
        countdown=countdown,
        preview_store=preview_store,
        orchestrator=orchestrator,
        a2s=a2s,
        call_tracker=call_tracker,
        runtime_state=runtime_state,
        power_tracker=power_tracker,
        commit_code=commit_code,
    )

  return ApplicationContainer(
      repo=repo,
      runtime_state=runtime_state,
      power_tracker=power_tracker,
      call_tracker=call_tracker,
      ptero=ptero,
      real_steam=real_steam,
      steam=steam,
      discord=discord,
      a2s=a2s,
      countdown=countdown,
      preview_store=preview_store,
      simulator_store=simulator_store,
      announcements=announcements,
      orchestrator=orchestrator,
      server_service=server_service,
      status_service=status_service,
      commit_code=commit_code,
      http_client=http_client,
  )


def bind_container_to_app(app: FastAPI, container: ApplicationContainer) -> None:
  """Binds all container components to FastAPI app.state for request dependencies and template rendering."""
  app.state.commit_code = container.commit_code
  app.state.repo = container.repo
  app.state.runtime_state = container.runtime_state
  app.state.power_tracker = container.power_tracker
  app.state.ptero = container.ptero
  app.state.steam = container.steam
  app.state.discord = container.discord
  app.state.a2s = container.a2s
  app.state.countdown = container.countdown
  app.state.preview_store = container.preview_store
  app.state.simulator_store = container.simulator_store
  app.state.orchestrator = container.orchestrator
  app.state.server_service = container.server_service
  app.state.status_service = container.status_service
  app.state.announcements = container.announcements
  app.state.call_tracker = container.call_tracker
  app.state.server_config_service = getattr(
      container.server_service, "config_service", None
  )
  app.state.server_power_service = getattr(
      container.server_service, "power_service", None
  )
  app.state.inspection_service = getattr(
      container.orchestrator, "inspection_service", None
  )
  app.state.countdown_coordinator = getattr(
      container.orchestrator, "countdown_coordinator", None
  )
  app.state.container = container


async def shutdown_container(container: ApplicationContainer) -> None:
  """Gracefully stops background tasks, cancels active countdowns, and cleans up resources."""
  try:
    orchestrator = container.orchestrator
    if orchestrator:
      orchestrator.stop_loop()
      cancelled_tasks = orchestrator.cancel_all_countdowns(
          reason="Application shutdown"
      )
      if cancelled_tasks:
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
      if getattr(orchestrator, "loop_task", None):
        try:
          await orchestrator.loop_task
        except asyncio.CancelledError:
          pass
  except Exception as e:
    logger.error("Error shutting down orchestrator: %s", e)
  finally:
    if container.http_client:
      await close_resources(container.http_client)


__all__ = [
    "ApplicationContainer",
    "create_announcement_service",
    "create_update_orchestrator",
    "create_status_service",
    "create_server_service",
    "build_container",
    "bind_container_to_app",
    "shutdown_container",
]
