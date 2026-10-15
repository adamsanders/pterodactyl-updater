import asyncio
from datetime import datetime
import logging
from typing import Optional
from app.core.models import ServerModel, WebhookPreview
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    NotificationGateway,
    PterodactylGateway,
    SteamGateway,
)
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
      discord: NotificationGateway,
      preview_store: WebhookPreviewStore,
      countdown: CountdownManagerProtocol,
      simulator_store: Optional[BuildSimulatorStore] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.discord = discord
    self.preview_store = preview_store
    self.countdown = countdown
    self.simulator_store = simulator_store
    self._restarted_builds: dict[str, str] = {}

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
    cfg = self.repo.load()
    msg = (
        f"Server will restart in {minutes_left} minute(s) for an update. Please find a safe spot!"
    )
    is_first = minutes_left == 15

    if is_first or server.warn_ingame_countdown:
      logger.info(f"[{server.name}] {msg}")
      await self.ptero.send_command(
          cfg.panel_url, cfg.api_key, server.server_id, f"say {msg}"
      )

    if cfg.discord_webhook and (
        server.discord_alerts and (is_first or server.warn_discord_countdown)
    ):
      embed = (
          await self.steam.fetch_patchnotes(server.app_id)
          if include_patchnotes
          else None
      )
      if cfg.test_mode:
        self.preview_store.set_preview(
            WebhookPreview(
                server_name=server.name,
                message=f"⚠️ **[{server.name}]** {msg}",
                embed=embed,
                timestamp=datetime.now().strftime("%I:%M %p"),
            )
        )
      else:
        await self.discord.send_notification(
            webhook_url=cfg.discord_webhook,
            message=f"⚠️ **[{server.name}]** {msg}",
            embed=embed,
        )

  async def delayed_restart_routine(self, server: ServerModel) -> None:
    cfg = self.repo.load()
    self.countdown.start(server.server_id, 900)
    # Schedule: 15m left -> sleep 5m (300s) until 10m
    #           10m left -> sleep 5m (300s) until 5m
    #            5m left -> sleep 4m (240s) until 1m
    #            1m left -> sleep 1m (60s)  until 0m (restart)
    # Total elapsed sleep time = 300 + 300 + 240 + 60 = 900 seconds (15 minutes)
    warning_schedule = [
        (15, 5 * 60),
        (10, 5 * 60),
        (5, 4 * 60),
        (1, 1 * 60),
    ]
    try:
      for mins, sleep_secs in warning_schedule:
        await self.broadcast_warning(
            server=server, minutes_left=mins, include_patchnotes=(mins == 15)
        )
        await asyncio.sleep(sleep_secs)

      logger.info(
          f"[{server.name}] 15-minute countdown ended. Restarting server via Pterodactyl API."
      )
      server.last_status = "Restarting server via Pterodactyl API..."
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
    if ptero_name:
      server.name = ptero_name

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

    # 3. Retrieve SteamCMD build info (always query to detect new/withdrawn/simulated builds)
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
    cfg.last_check = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not cfg.panel_url or not cfg.api_key or not cfg.servers:
      cfg.last_status = "Setup Incomplete."
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

    cfg.last_status = (
        f"Checked {len(servers_to_check)} server(s) successfully."
    )
    self.repo.save(cfg)

  async def start_background_loop(self) -> None:
    while True:
      try:
        await self.run_update_check()
      except Exception as e:
        logger.error(f"Scheduler exception: {e}")
      cfg = self.repo.load()
      await asyncio.sleep(max(cfg.check_interval, 1) * 60)