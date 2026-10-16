import asyncio
from datetime import datetime
import logging
import time
from typing import Optional

from app.core.config import TIMING_CONFIG
from app.core.models import ServerModel
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
from app.services.preview_store import WebhookPreviewStore

logger = logging.getLogger("updater.orchestrator")

TRANSITIONAL_POWER_STATES = frozenset({"starting", "stopping"})


class UpdateOrchestrator:

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
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.countdown = countdown
    self.simulator_store = simulator_store
    self.runtime_state = runtime_state
    self._restarted_builds: dict[str, str] = {}

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

  @property
  def discord(self) -> Optional[NotificationGateway]:
    return self.announcements.discord

  @property
  def preview_store(self) -> Optional[WebhookPreviewStore]:
    return self.announcements.preview_store

  def clear_restarted_build(self, server_id: Optional[str] = None) -> None:
    if server_id:
      self._restarted_builds.pop(server_id, None)
    else:
      self._restarted_builds.clear()

  async def broadcast_warning(
      self,
      server: ServerModel,
      minutes_left: int,
      include_patchnotes: bool = False,
  ) -> None:
    await self.announcements.broadcast_warning(
        server=server,
        minutes_left=minutes_left,
        include_patchnotes=include_patchnotes,
    )

  async def delayed_restart_routine(self, server: ServerModel) -> None:
    cfg = self.repo.load()
    total_seconds = TIMING_CONFIG.total_duration_seconds()
    self.countdown.start(server.server_id, total_seconds)
    warning_schedule = TIMING_CONFIG.compute_warning_schedule()
    first_min = warning_schedule[0][0] if warning_schedule else 15
    try:
      for mins, sleep_secs in warning_schedule:
        await self.broadcast_warning(
            server=server, minutes_left=mins, include_patchnotes=(mins == first_min)
        )
        await asyncio.sleep(sleep_secs)

      logger.info(
          f"[{server.name}] {total_seconds // 60}-minute countdown ended. Restarting server via Pterodactyl API."
      )
      server.last_status = "Restarting server via Pterodactyl API..."
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=server.last_status,
        )
      self._restarted_builds[server.server_id] = server.latest_build
      self.countdown.stop(server.server_id)
      await self.ptero.trigger_restart(
          cfg.panel_url, cfg.api_key, server.server_id
      )
    except asyncio.CancelledError:
      logger.info(
          f"[{server.name}] Scheduled update countdown was cancelled."
      )
      raise
    finally:
      self.countdown.stop(server.server_id)

  async def _evaluate_build_status(
      self,
      server: ServerModel,
      latest_build: Optional[str],
      local_build: Optional[str],
      read_error: Optional[str],
      power_state: str = "running",
  ) -> None:
    if latest_build:
      server.latest_build = latest_build
    if local_build:
      server.current_build = local_build

    if read_error:
      server.last_status = f"Error: {read_error}"
    elif not latest_build:
      server.last_status = "Error: Unreachable SteamCMD API"
    elif latest_build == local_build:
      if self.countdown.is_running(server.server_id):
        self.countdown.stop(server.server_id)
      self._restarted_builds.pop(server.server_id, None)
      server.last_status = "Up to date"
    else:
      if self.countdown.is_running(server.server_id):
        server.last_status = "Update Available — Countdown Started"
      elif self._restarted_builds.get(server.server_id) == latest_build:
        server.last_status = "Restart dispatched — waiting for build update"
      elif server.auto_restart and power_state == "running":
        server.last_status = "Update Available — Countdown Started"
        task = asyncio.create_task(self.delayed_restart_routine(server))
        self.countdown.attach_task(server.server_id, task)
      else:
        server.last_status = "Update Available"

    if self.runtime_state and server.server_id:
      self.runtime_state.update_server_state(
          server_id=server.server_id,
          current_build=server.current_build,
          latest_build=server.latest_build,
          last_status=server.last_status,
      )

  async def _inspect_server(
      self,
      server: ServerModel,
      panel_url: str,
      api_key: str,
      steam_build_cache: dict[str, Optional[str]],
  ) -> None:
    if not server.server_id:
      return

    # 1. Synchronize server name
    ptero_name, _ = await self.ptero.get_server_name(
        panel_url, api_key, server.server_id
    )
    if ptero_name and server.name != ptero_name:
      logger.info(
          f"[{server.name}] Synchronized name from Pterodactyl: '{ptero_name}'"
      )
      server.name = ptero_name
      cfg_disk = self.repo.load()
      match_idx = next(
          (
              i
              for i, s in enumerate(cfg_disk.servers)
              if s.server_id == server.server_id
          ),
          None,
      )
      if (
          match_idx is not None
          and cfg_disk.servers[match_idx].name != ptero_name
      ):
        cfg_disk.servers[match_idx].name = ptero_name
        self.repo.save(cfg_disk)

    # 2. Check power state
    power_state = await self.ptero.get_power_state(
        panel_url, api_key, server.server_id
    )

    # 2a. If manual restart/stop occurred externally during countdown, abort it
    if self.countdown.is_running(server.server_id) and power_state in (
        "starting",
        "stopping",
        "offline",
    ):
      logger.info(
          f"[{server.name}] Power state is '{power_state}' during active"
          " countdown. Cancelling auto-restart."
      )
      self.countdown.stop(server.server_id)
      self._restarted_builds.pop(server.server_id, None)
      server.last_status = (
          f"Manual {power_state} detected — countdown cancelled"
      )
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=server.last_status,
        )

    # 3. Retrieve SteamCMD build info (always query to detect new/withdrawn/simulated builds)
    if not server.app_id:
      server.last_status = "App ID not configured"
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=server.last_status,
        )
      return

    if self.simulator_store and self.simulator_store.has_simulated_build(
        server.server_id
    ):
      latest_build = await self.steam.get_latest_build(
          server.app_id, server_id=server.server_id
      )
    else:
      if server.app_id not in steam_build_cache:
        steam_build_cache[server.app_id] = await self.steam.get_latest_build(
            server.app_id
        )
      latest_build = steam_build_cache[server.app_id]

    if latest_build:
      server.latest_build = latest_build

    # 4. Immediate build convergence check (e.g. Test Mode disabled or build withdrawn)
    if (
        latest_build
        and server.current_build not in ("Unknown", "?")
        and latest_build == server.current_build
    ):
      if self.countdown.is_running(server.server_id):
        logger.info(
            f"[{server.name}] Latest build ({latest_build}) matches current"
            " build. Aborting countdown."
        )
        self.countdown.stop(server.server_id)
      self._restarted_builds.pop(server.server_id, None)
      server.last_status = "Up to date"
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            current_build=server.current_build,
            latest_build=latest_build,
            last_status=server.last_status,
        )
      return

    # 5. Skip local manifest I/O if server is starting/stopping, or offline following update restart
    if power_state in TRANSITIONAL_POWER_STATES or (
        power_state == "offline"
        and self._restarted_builds.get(server.server_id) == latest_build
    ):
      logger.info(
          f"[{server.name}] Server is '{power_state}'. Skipping manifest I/O"
          " this cycle."
      )
      return

    # 6. Read local container manifest (safe when Online or Offline)
    if not server.manifest_path:
      server.last_status = "Manifest path not configured"
      if self.runtime_state and server.server_id:
        self.runtime_state.update_server_state(
            server_id=server.server_id,
            last_status=server.last_status,
        )
      return

    local_build, err = await self.ptero.get_local_build(
        panel_url, api_key, server.server_id, server.manifest_path
    )

    # 7. Evaluate status and progression
    await self._evaluate_build_status(
        server, latest_build, local_build, err, power_state
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
        power = await self.ptero.get_power_state(
            cfg.panel_url, cfg.api_key, srv.server_id
        )
        if power in ("starting", "stopping", "offline"):
          logger.info(
              f"[{srv.name}] External power state '{power}' detected."
              " Cancelling auto-restart countdown."
          )
          self.countdown.stop(srv.server_id)
          self._restarted_builds.pop(srv.server_id, None)
          status_msg = f"Manual {power} detected — countdown cancelled"
          srv.last_status = status_msg
          if self.runtime_state:
            self.runtime_state.update_server_state(
                srv.server_id, last_status=status_msg
            )
          else:
            self.repo.save(cfg)

  async def start_background_loop(self) -> None:
    last_full_check = 0.0
    while True:
      try:
        now = time.time()
        cfg = self.repo.load()
        interval_secs = max(cfg.check_interval, 1) * 60

        if now - last_full_check >= interval_secs:
          await self.run_update_check()
          last_full_check = time.time()

        await self.monitor_server_lifecycle()
      except Exception as e:
        logger.error(f"Scheduler exception: {e}")

      await asyncio.sleep(2)