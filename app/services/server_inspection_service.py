import logging
from typing import Optional

from app.core.models import PowerState, ServerModel, ServerUpdateStatus
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
)
from app.services.build_simulator import BuildSimulatorStore
from app.services.countdown_coordinator_service import CountdownCoordinatorService

logger = logging.getLogger("updater.server_inspection")

TRANSITIONAL_POWER_STATES = frozenset({PowerState.STARTING, PowerState.STOPPING})


class ServerInspectionService:
  """Responsible for Steam Web API build checks, local ACF manifest reading, and build diff evaluation."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      countdown_coordinator: CountdownCoordinatorService,
      countdown: Optional[CountdownManagerProtocol] = None,
      simulator_store: Optional[BuildSimulatorStore] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      restarted_builds: Optional[dict[str, str]] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.countdown_coordinator = countdown_coordinator
    self.countdown = countdown or countdown_coordinator.countdown
    self.simulator_store = simulator_store
    self.runtime_state = runtime_state
    self._restarted_builds = (
        restarted_builds
        if restarted_builds is not None
        else countdown_coordinator._restarted_builds
    )

  async def evaluate_build_status(
      self,
      server: ServerModel,
      latest_build: Optional[str],
      local_build: Optional[str],
      read_error: Optional[str],
      power_state: PowerState | str = PowerState.RUNNING,
  ) -> None:
    """Evaluates differences between Steam remote build and local container manifest."""
    p_state = PowerState.from_str(power_state)
    if latest_build:
      server.latest_build = latest_build
    if local_build:
      server.current_build = local_build

    if read_error:
      server.last_status = f"Error: {read_error}"
    elif not latest_build:
      server.last_status = f"{ServerUpdateStatus.ERROR}: Unreachable SteamCMD API"
    elif latest_build == local_build:
      if self.countdown.is_running(server.server_id):
        self.countdown.stop(server.server_id)
      self._restarted_builds.pop(server.server_id, None)
      server.last_status = ServerUpdateStatus.UP_TO_DATE
    else:
      if self.countdown.is_running(server.server_id):
        server.last_status = ServerUpdateStatus.COUNTDOWN_ACTIVE
      elif self._restarted_builds.get(server.server_id) == latest_build:
        server.last_status = ServerUpdateStatus.RESTART_DISPATCHED
      elif server.auto_restart and p_state == PowerState.RUNNING:
        server.last_status = ServerUpdateStatus.COUNTDOWN_ACTIVE
        self.countdown_coordinator.start_countdown(server)
      else:
        server.last_status = ServerUpdateStatus.UPDATE_AVAILABLE

    if self.runtime_state and server.server_id:
      self.runtime_state.update_server_state(
          server_id=server.server_id,
          current_build=server.current_build,
          latest_build=server.latest_build,
          last_status=server.last_status,
      )

  async def inspect_server(
      self,
      server: ServerModel,
      panel_url: str,
      api_key: str,
      steam_build_cache: dict[str, Optional[str]],
  ) -> None:
    """Executes single server inspection pipeline: name sync, power check, Steam query, manifest read, and diff evaluation."""
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
      if match_idx is not None:
        cfg_disk.servers[match_idx].name = ptero_name
        self.repo.save(cfg_disk)

    # 2. Check power state
    power_state = PowerState.from_str(
        await self.ptero.get_power_state(panel_url, api_key, server.server_id)
    )

    # 2a. If manual restart/stop occurred externally during countdown, abort it
    if self.countdown.is_running(server.server_id) and power_state in (
        PowerState.STARTING,
        PowerState.STOPPING,
        PowerState.OFFLINE,
    ):
      logger.info(
          f"[{server.name}] Power state is '{power_state}' during active"
          " countdown. Cancelling auto-restart."
      )
      self.countdown_coordinator.cancel_active_countdown(
          server, reason=f"Manual {power_state} detected"
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

    # 4. Skip local manifest I/O if server is starting/stopping, or offline following update restart
    if power_state in TRANSITIONAL_POWER_STATES or (
        power_state == PowerState.OFFLINE
        and self._restarted_builds.get(server.server_id) == latest_build
    ):
      logger.info(
          f"[{server.name}] Server is '{power_state}'. Skipping manifest I/O"
          " this cycle."
      )
      return

    # 5. Read local container manifest (safe when Online or Offline)
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

    # 6. Evaluate status and progression
    await self.evaluate_build_status(
        server, latest_build, local_build, err, power_state
    )
