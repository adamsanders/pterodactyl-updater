import asyncio
from datetime import datetime
import logging
import time
from typing import Optional

from app.core.models import PowerState, ServerModel, ServerUpdateStatus
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    NotificationGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
)
from app.services.announcement_service import AnnouncementService
from app.services.build_simulator import BuildSimulatorStore
from app.services.countdown_coordinator_service import CountdownCoordinatorService
from app.services.preview_store import WebhookPreviewStore
from app.services.server_inspection_service import ServerInspectionService

logger = logging.getLogger("updater.orchestrator")


class UpdateOrchestrator:
  """Top-level loop coordinator orchestrating fleet inspection and restart workflows."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      countdown: CountdownManagerProtocol,
      announcements: Optional[AnnouncementService] = None,
      discord: Optional[NotificationGateway] = None,
      preview_store: Optional[WebhookPreviewStore] = None,
      simulator_store: Optional[BuildSimulatorStore] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      inspection_service: Optional[ServerInspectionService] = None,
      countdown_coordinator: Optional[CountdownCoordinatorService] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.countdown = countdown
    self.simulator_store = simulator_store
    self.runtime_state = runtime_state
    self._restarted_builds: dict[str, str] = {}
    self._loop_task: Optional[asyncio.Task] = None
    self._running: bool = False

    if announcements is not None:
      self.announcements = announcements
    else:
      self.announcements = AnnouncementService(
          repository=repository,
          ptero=ptero,
          steam=steam,
          discord=discord,
          preview_store=preview_store,
      )

    if countdown_coordinator is not None:
      self.countdown_coordinator = countdown_coordinator
      self._restarted_builds = countdown_coordinator._restarted_builds
    else:
      self.countdown_coordinator = CountdownCoordinatorService(
          repository=repository,
          ptero=ptero,
          countdown=countdown,
          announcements=self.announcements,
          runtime_state=runtime_state,
          restarted_builds=self._restarted_builds,
      )

    if inspection_service is not None:
      self.inspection_service = inspection_service
    else:
      self.inspection_service = ServerInspectionService(
          repository=repository,
          ptero=ptero,
          steam=steam,
          countdown_coordinator=self.countdown_coordinator,
          countdown=countdown,
          simulator_store=simulator_store,
          runtime_state=runtime_state,
          restarted_builds=self._restarted_builds,
      )

  @property
  def discord(self) -> Optional[NotificationGateway]:
    return self.announcements.discord

  @property
  def preview_store(self) -> Optional[WebhookPreviewStore]:
    return self.announcements.preview_store

  def clear_restarted_build(self, server_id: Optional[str] = None) -> None:
    self.countdown_coordinator.clear_restarted_build(server_id)

  async def broadcast_warning(
      self,
      server: ServerModel,
      minutes_left: int,
      include_patchnotes: bool = False,
  ) -> None:
    await self.countdown_coordinator.broadcast_warning(
        server=server,
        minutes_left=minutes_left,
        include_patchnotes=include_patchnotes,
    )

  async def delayed_restart_routine(self, server: ServerModel) -> None:
    await self.countdown_coordinator.delayed_restart_routine(server)

  def start_countdown(self, server: ServerModel) -> asyncio.Task:
    return self.countdown_coordinator.start_countdown(server)

  def cancel_active_countdown(
      self, server: ServerModel, reason: str = ""
  ) -> None:
    self.countdown_coordinator.cancel_active_countdown(server, reason=reason)

  async def _evaluate_build_status(
      self,
      server: ServerModel,
      latest_build: Optional[str],
      local_build: Optional[str],
      read_error: Optional[str],
      power_state: PowerState | str = PowerState.RUNNING,
  ) -> None:
    await self.inspection_service.evaluate_build_status(
        server=server,
        latest_build=latest_build,
        local_build=local_build,
        read_error=read_error,
        power_state=power_state,
    )

  async def _inspect_server(
      self,
      server: ServerModel,
      panel_url: str,
      api_key: str,
      steam_build_cache: dict[str, Optional[str]],
  ) -> None:
    await self.inspection_service.inspect_server(
        server=server,
        panel_url=panel_url,
        api_key=api_key,
        steam_build_cache=steam_build_cache,
    )

  async def run_update_check(
      self, target_server_id: Optional[str] = None
  ) -> None:
    cfg = self.repo.load()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg.last_check = now_str
    if self.runtime_state:
      self.runtime_state.update_global_state(last_check=now_str)

    if not cfg.panel_url or not cfg.api_key or not cfg.servers:
      cfg.last_status = "Setup Incomplete."
      if self.runtime_state:
        self.runtime_state.update_global_state(last_status="Setup Incomplete.")
      else:
        self.repo.save(cfg)
      return

    servers_to_check = [
        srv
        for srv in cfg.servers
        if not target_server_id or srv.server_id == target_server_id
    ]

    steam_build_cache: dict[str, Optional[str]] = {}
    for srv in servers_to_check:
      await self._inspect_server(
          srv, cfg.panel_url, cfg.api_key, steam_build_cache
      )

    status_str = f"Checked {len(servers_to_check)} server(s) successfully."
    cfg.last_status = status_str
    if self.runtime_state:
      self.runtime_state.update_global_state(last_status=status_str)
    else:
      self.repo.save(cfg)

  async def monitor_server_lifecycle(self) -> None:
    """Monitors power transitions and countdown cancellations in the background."""
    cfg = self.repo.load()
    if not cfg.panel_url or not cfg.api_key:
      return

    for srv in cfg.servers:
      if not srv.server_id:
        continue

      # 1. Startup transition inspection
      if self.ptero.consume_startup_transition(srv.server_id):
        logger.info(
            f"[{srv.name}] Startup transition detected in background monitor."
            " Triggering inspection."
        )
        asyncio.create_task(
            self.run_update_check(target_server_id=srv.server_id)
        )

      # 2. External power change cancelling active countdown
      if self.countdown.is_running(srv.server_id):
        power = PowerState.from_str(
            await self.ptero.get_power_state(
                cfg.panel_url, cfg.api_key, srv.server_id
            )
        )
        if power in (PowerState.STARTING, PowerState.STOPPING, PowerState.OFFLINE):
          logger.info(
              f"[{srv.name}] External power state '{power}' detected."
              " Cancelling auto-restart countdown."
          )
          self.countdown_coordinator.cancel_active_countdown(
              srv, reason=f"Manual {power} detected"
          )
          if not self.runtime_state:
            self.repo.save(cfg)

  def start_loop(self) -> asyncio.Task:
    """Starts the background loop as an asyncio Task and returns the task handle."""
    if self._loop_task is None or self._loop_task.done():
      self._running = True
      self._loop_task = asyncio.create_task(self.start_background_loop())
    return self._loop_task

  def stop_loop(self) -> None:
    """Gracefully halts the active background loop task."""
    self._running = False
    if self._loop_task and not self._loop_task.done():
      self._loop_task.cancel()

  async def start_background_loop(self) -> None:
    self._running = True
    last_full_check = 0.0
    while self._running:
      try:
        now = time.time()
        cfg = self.repo.load()
        interval_secs = max(cfg.check_interval, 1) * 60

        if now - last_full_check >= interval_secs:
          await self.run_update_check()
          last_full_check = time.time()

        await self.monitor_server_lifecycle()
      except asyncio.CancelledError:
        break
      except Exception as e:
        logger.error(f"Scheduler exception: {e}")

      try:
        await asyncio.sleep(2)
      except asyncio.CancelledError:
        break