from datetime import datetime
import logging
from typing import List, Optional, Union
from app.core.exceptions import (
    ConfigurationError,
    PterodactylApiError,
    ServerNotFoundError,
    SimulationError,
)
from app.core.models import (
    OperationResult,
    PowerSignal,
    ServerModel,
    ServerUpdateStatus,
    SettingsUpdateDTO,
    WebhookPreview,
)
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    NotificationGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
    UpdateOrchestratorProtocol,
)
from app.services.announcement_service import AnnouncementService
from app.services.build_simulator import BuildSimulatorStore
from app.services.preview_store import WebhookPreviewStore

logger = logging.getLogger("updater.server_service")


class ServerService:

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      simulator_store: BuildSimulatorStore,
      countdown: CountdownManagerProtocol,
      announcements: Optional[AnnouncementService] = None,
      discord: Optional[NotificationGateway] = None,
      preview_store: Optional[WebhookPreviewStore] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      orchestrator: Optional[UpdateOrchestratorProtocol] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.simulator_store = simulator_store
    self.countdown = countdown
    self.runtime_state = runtime_state
    self.orchestrator = orchestrator

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

  def save_settings(self, settings: SettingsUpdateDTO) -> None:
    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.ssl_verify = settings.ssl_verify
    cfg.servers = list(settings.servers)
    self.repo.save(cfg)

    if self.runtime_state:
      new_ids = {str(s.server_id).strip().lower() for s in settings.servers if s.server_id}
      existing_ids = list(self.runtime_state.get_all_server_states().keys())
      for old_id in existing_ids:
        if old_id not in new_ids:
          self.runtime_state.remove_server_state(old_id)
      for s in settings.servers:
        if s.server_id:
          self.runtime_state.get_server_state(s.server_id)

  def add_server(self, settings: SettingsUpdateDTO) -> None:
    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.ssl_verify = settings.ssl_verify
    cfg.servers = list(settings.servers)
    cfg.servers.append(ServerModel())
    self.repo.save(cfg)

    if self.runtime_state:
      new_ids = {str(s.server_id).strip().lower() for s in cfg.servers if s.server_id}
      existing_ids = list(self.runtime_state.get_all_server_states().keys())
      for old_id in existing_ids:
        if old_id not in new_ids:
          self.runtime_state.remove_server_state(old_id)
      for s in cfg.servers:
        if s.server_id:
          self.runtime_state.get_server_state(s.server_id)

  def find_server_index(
      self, servers: List[ServerModel], identifier: Union[str, int]
  ) -> Optional[int]:
    """Finds server index in the server collection by server_id or legacy numeric index."""
    ident_str = str(identifier).strip()
    if not ident_str:
      return None

    ident_lower = ident_str.lower()
    # 1. Match by server_id (case-insensitive)
    for idx, srv in enumerate(servers):
      if srv.server_id and srv.server_id.strip().lower() == ident_lower:
        return idx

    # 2. Match by legacy numeric index if identifier is numeric
    try:
      numeric_idx = int(identifier)
      if 0 <= numeric_idx < len(servers):
        return numeric_idx
    except (ValueError, TypeError):
      pass

    return None

  def delete_server(
      self, identifier: Union[str, int], settings: SettingsUpdateDTO
  ) -> None:
    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.ssl_verify = settings.ssl_verify
    cfg.servers = list(settings.servers)
    target_idx = self.find_server_index(cfg.servers, identifier)
    removed_server_id = None
    if target_idx is not None:
      removed_srv = cfg.servers.pop(target_idx)
      removed_server_id = removed_srv.server_id
    self.repo.save(cfg)
    if self.runtime_state:
      if removed_server_id:
        self.runtime_state.remove_server_state(removed_server_id)
      elif isinstance(identifier, str):
        self.runtime_state.remove_server_state(identifier)
      active_ids = {str(s.server_id).strip().lower() for s in cfg.servers if s.server_id}
      for old_id in list(self.runtime_state.get_all_server_states().keys()):
        if old_id not in active_ids:
          self.runtime_state.remove_server_state(old_id)

  async def rename_server(
      self, identifier: Union[str, int], new_name: str, settings: SettingsUpdateDTO
  ) -> bool:
    if not new_name:
      return False

    idx = self.find_server_index(settings.servers, identifier)
    if idx is None:
      return False

    target_server = settings.servers[idx]
    success, err = await self.ptero.rename_server(
        settings.panel_url, settings.api_key, target_server.server_id, new_name
    )

    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.ssl_verify = settings.ssl_verify
    cfg.servers = list(settings.servers)

    repo_idx = self.find_server_index(cfg.servers, identifier)
    if repo_idx is not None:
      if success:
        cfg.servers[repo_idx].name = new_name
        cfg.servers[repo_idx].last_status = "Renamed in Pterodactyl"
        if self.runtime_state:
          self.runtime_state.update_server_state(
              target_server.server_id, last_status="Renamed in Pterodactyl"
          )
      else:
        cfg.servers[repo_idx].last_status = f"Rename failed: {err}"
        if self.runtime_state:
          self.runtime_state.update_server_state(
              target_server.server_id, last_status=f"Rename failed: {err}"
          )

    self.repo.save(cfg)
    return success

  async def send_power_action(
      self, identifier: Union[str, int], action: Union[PowerSignal, str]
  ) -> OperationResult:
    try:
      sig = PowerSignal.from_str(action)
    except (ValueError, TypeError):
      return OperationResult(
          False,
          f"Invalid power action '{action}'.",
          status_code=400,
          error_type="InvalidPowerAction",
      )

    cfg = self.repo.load()
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      return OperationResult(
          False,
          "Server index out of range.",
          status_code=404,
          error_type="ServerNotFound",
      )

    server = cfg.servers[idx]
    if not cfg.panel_url or not cfg.api_key or not server.server_id:
      return OperationResult(
          False,
          "Server ID or Panel API Key configuration is incomplete.",
          status_code=400,
          error_type="ConfigurationError",
      )

    # Invalidate orchestrator restart suppression on manual power signal
    if self.orchestrator:
      self.orchestrator.clear_restarted_build(server.server_id)

    # Restart, stop, or kill cancels any pending update countdown
    if sig in (PowerSignal.RESTART, PowerSignal.STOP, PowerSignal.KILL):
      if self.countdown.is_running(server.server_id):
        logger.info(
            f"[{server.name}] Power action '{sig}' triggered."
            " Cancelling active auto-restart countdown."
        )
        self.countdown.stop(server.server_id)
        status_msg = f"Countdown cancelled ({sig} requested)"
        server.last_status = status_msg
        if self.runtime_state:
          self.runtime_state.update_server_state(
              server.server_id, last_status=status_msg
          )
        self.repo.save(cfg)

    return await self.ptero.send_power_signal(
        panel_url=cfg.panel_url,
        api_key=cfg.api_key,
        server_id=server.server_id,
        signal=sig,
    )

  async def test_webhook(self, identifier: Union[str, int]) -> None:
    cfg = self.repo.load()
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      return

    server = cfg.servers[idx]
    _, status_msg = await self.announcements.send_test_alert(server)
    server.last_status = status_msg
    if self.runtime_state:
      self.runtime_state.update_server_state(
          server.server_id, last_status=status_msg
      )
    self.repo.save(cfg)

  def simulate_build_update(
      self, identifier: Union[str, int], new_build_id: str
  ) -> tuple[bool, Optional[str], Optional[str]]:
    cfg = self.repo.load()
    if not cfg.test_mode:
      return False, "Test Mode is not enabled.", None
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      return False, "Server index out of range.", None

    server = cfg.servers[idx]
    # Clear previous simulations so only this selected server is targeted
    self.simulator_store.clear_simulated_build()
    self.simulator_store.set_simulated_build(server.server_id, new_build_id)
    return True, None, server.server_id

  async def trigger_simulated_build(
      self, identifier: Union[str, int], new_build_id: str
  ) -> str:
    """Coordinates simulation store configuration, build clearing, and orchestrator inspection."""
    success, err, target_server_id = self.simulate_build_update(
        identifier, new_build_id
    )
    if not success:
      raise SimulationError(err or "Simulation failed")

    if self.orchestrator and target_server_id:
      self.orchestrator.clear_restarted_build(target_server_id)
      await self.orchestrator.run_update_check(target_server_id=target_server_id)

    return target_server_id or str(identifier)

  async def toggle_test_mode(self, enabled: bool) -> bool:
    cfg = self.repo.load()
    cfg.test_mode = enabled
    if not enabled:
      self.simulator_store.clear_simulated_build()
      # Abort any countdowns initiated during simulation
      for srv in cfg.servers:
        if self.countdown.is_running(srv.server_id):
          self.countdown.stop(srv.server_id)
          srv.last_status = ServerUpdateStatus.IDLE
          if self.runtime_state:
            self.runtime_state.update_server_state(
                srv.server_id,
                last_status=ServerUpdateStatus.IDLE,
            )
    self.repo.save(cfg)
    if self.orchestrator:
      self.orchestrator.clear_restarted_build()
      if not enabled:
        await self.orchestrator.run_update_check()
    return enabled

  async def trigger_immediate_check(self) -> None:
    """Invalidates power cache and executes immediate fleet update check."""
    self.ptero.invalidate_power_cache()
    if self.orchestrator:
      await self.orchestrator.run_update_check()

  async def lookup_server_name(self, server_id: str) -> str:
    """Looks up server name from Pterodactyl Panel for a given server ID without saving."""
    sid = server_id.strip()
    if not sid:
      raise ConfigurationError("Server ID cannot be empty.")
    cfg = self.repo.load()
    if not cfg.panel_url or not cfg.api_key:
      raise ConfigurationError(
          "Pterodactyl Panel URL and API Key must be configured first."
      )
    res = await self.ptero.get_server_name(
        cfg.panel_url, cfg.api_key, sid, raise_on_error=True
    )
    return res.name or ""

  async def sync_server_name(
      self, identifier: Union[str, int], server_id_override: Optional[str] = None
  ) -> str:
    """Fetches latest server name from Pterodactyl and persists it to repository configuration."""
    cfg = self.repo.load()
    if not cfg.panel_url or not cfg.api_key:
      raise ConfigurationError(
          "Pterodactyl Panel URL and API Key must be configured first."
      )

    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))

    sid = (server_id_override or cfg.servers[idx].server_id).strip()
    if not sid:
      raise ConfigurationError("Server ID cannot be empty.")

    res = await self.ptero.get_server_name(
        cfg.panel_url, cfg.api_key, sid, raise_on_error=True
    )
    if not res.name:
      raise PterodactylApiError(
          "Server name could not be resolved from panel.", server_id=sid
      )

    old_sid = cfg.servers[idx].server_id
    cfg.servers[idx].name = res.name
    if server_id_override:
      cfg.servers[idx].server_id = sid
    self.repo.save(cfg)
    if (
        self.runtime_state
        and server_id_override
        and old_sid
        and old_sid.strip().lower() != sid.strip().lower()
    ):
      self.runtime_state.rename_server_state(old_sid, sid)
    return res.name

  def update_server_toggle(
      self, identifier: Union[str, int], field: str, value: bool
  ) -> None:
    """Toggles and immediately persists a single boolean setting on a server."""
    allowed_fields = {
        "auto_restart",
        "discord_alerts",
        "warn_ingame_countdown",
        "warn_discord_countdown",
    }
    if field not in allowed_fields:
      raise ConfigurationError(
          f"Invalid toggle field '{field}'. Allowed fields: {allowed_fields}"
      )

    cfg = self.repo.load()
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))

    setattr(cfg.servers[idx], field, bool(value))
    self.repo.save(cfg)

  async def save_single_server(
      self, identifier: Union[str, int], data: dict
  ) -> ServerModel:
    """Persists text configuration changes for a specific server card."""
    cfg = self.repo.load()
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))

    srv = cfg.servers[idx]
    old_server_id = srv.server_id
    if "server_id" in data:
      srv.server_id = str(data["server_id"]).strip()
    if "app_id" in data:
      srv.app_id = str(data["app_id"]).strip()
    if "manifest_path" in data:
      srv.manifest_path = str(data["manifest_path"]).strip()
    found_offset = False
    for key in ("query_port_offset", "port_offset", "srv_port_offset", "srv_query_port_offset"):
      if key in data:
        try:
          srv.query_port_offset = int(data[key])
        except (ValueError, TypeError):
          srv.query_port_offset = 0
        found_offset = True
        break
    if not found_offset:
      for k, v in data.items():
        if any(
            k.startswith(pfx + "_")
            for pfx in ("srv_port_offset", "srv_query_port_offset", "port_offset", "query_port_offset")
        ):
          try:
            srv.query_port_offset = int(v)
          except (ValueError, TypeError):
            srv.query_port_offset = 0
          break

    name_input = str(data.get("name", "")).strip()
    if name_input and name_input != "New Server":
      srv.name = name_input
    elif srv.server_id and cfg.panel_url and cfg.api_key:
      try:
        res = await self.ptero.get_server_name(
            cfg.panel_url, cfg.api_key, srv.server_id
        )
        if res.name:
          srv.name = res.name
      except Exception:
        if name_input:
          srv.name = name_input
    self.repo.save(cfg)
    if self.runtime_state:
      if old_server_id and old_server_id.strip().lower() != srv.server_id.strip().lower():
        self.runtime_state.rename_server_state(old_server_id, srv.server_id)
      elif srv.server_id:
        self.runtime_state.get_server_state(srv.server_id)
    return srv

  async def detect_server_details(self, server_id: str) -> dict:
    """Queries Pterodactyl Panel to detect server name, Steam App ID, and manifest path."""
    sid = server_id.strip()
    if not sid:
      raise ConfigurationError("Server ID cannot be empty.")
    cfg = self.repo.load()
    if not cfg.panel_url or not cfg.api_key:
      raise ConfigurationError(
          "Pterodactyl Panel URL and API Key must be configured first."
      )
    return await self.ptero.detect_server_details(cfg.panel_url, cfg.api_key, sid)

  async def search_steam_games(self, query: str) -> list[dict]:
    """Searches Steam catalog and dedicated servers by query."""
    return await self.steam.search_games(query)