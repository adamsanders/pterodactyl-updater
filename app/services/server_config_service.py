import asyncio
import logging
from typing import List, Optional, Union

from app.core.exceptions import (
    ConfigurationError,
    PterodactylApiError,
    ServerNotFoundError,
)
from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    ServerModel,
    SteamSearchResult,
)
from app.web.schemas import (
    SettingsUpdateDTO,
    SingleServerSaveRequest,
)
from app.core.protocols import (
    ConfigRepositoryProtocol,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
)

logger = logging.getLogger("updater.server_config")


class _LockableOperation:
  """Ensures read-modify-write configuration cycles are serialized via asyncio.Lock."""

  def __init__(self, lock: asyncio.Lock, sync_fn, *args, **kwargs):
    self._lock = lock
    self._sync_fn = sync_fn
    self._args = args
    self._kwargs = kwargs

  def __await__(self):
    return self._run_async().__await__()

  async def _run_async(self):
    async with self._lock:
      return self._sync_fn(*self._args, **self._kwargs)


class ServerConfigService:
  """Dedicated service handling configuration CRUD, server provisioning, and per-server settings."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.runtime_state = runtime_state
    self._lock = asyncio.Lock()

  def find_server_index(
      self,
      servers_or_identifier: Union[List[ServerModel], AppConfigModel, str, int],
      identifier: Optional[Union[str, int]] = None,
  ) -> Optional[int]:
    """Finds server index in the server collection by server_id or legacy numeric index."""
    if identifier is None:
      cfg = self.repo.load()
      return cfg.find_server_index(servers_or_identifier)
    if isinstance(servers_or_identifier, AppConfigModel):
      return servers_or_identifier.find_server_index(identifier)
    return AppConfigModel.model_construct(servers=servers_or_identifier).find_server_index(identifier)

  def save_settings(self, settings: SettingsUpdateDTO):
    """Persists global settings and updates runtime state store tracking."""
    try:
      asyncio.get_running_loop()
      return _LockableOperation(self._lock, self._execute_save_settings, settings)
    except RuntimeError:
      return self._execute_save_settings(settings)

  def _execute_save_settings(self, settings: SettingsUpdateDTO) -> None:
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
      self.runtime_state.reconcile_with_servers(cfg.servers)

  def add_server(self, settings: SettingsUpdateDTO):
    """Appends a new unconfigured server template to configuration."""
    try:
      asyncio.get_running_loop()
      return _LockableOperation(self._lock, self._execute_add_server, settings)
    except RuntimeError:
      return self._execute_add_server(settings)

  def _execute_add_server(self, settings: SettingsUpdateDTO) -> None:
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
      self.runtime_state.reconcile_with_servers(cfg.servers)

  def delete_server(
      self, identifier: Union[str, int], settings: SettingsUpdateDTO
  ):
    """Deletes a server entry and cleans up ephemeral runtime telemetry."""
    try:
      asyncio.get_running_loop()
      return _LockableOperation(
          self._lock, self._execute_delete_server, identifier, settings
      )
    except RuntimeError:
      return self._execute_delete_server(identifier, settings)

  def _execute_delete_server(
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
    target_idx = cfg.find_server_index(identifier)
    if target_idx is not None:
      cfg.servers.pop(target_idx)
    self.repo.save(cfg)
    if self.runtime_state:
      self.runtime_state.reconcile_with_servers(cfg.servers)

  async def rename_server(
      self,
      identifier: Union[str, int],
      new_name: str,
      settings: SettingsUpdateDTO,
  ) -> bool:
    """Invokes Pterodactyl Panel rename API and synchronizes local configuration."""
    if not new_name:
      return False

    async with self._lock:
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

      repo_idx = cfg.find_server_index(identifier)
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
      self,
      identifier: Union[str, int],
      server_id_override: Optional[str] = None,
  ) -> str:
    """Fetches latest server name from Pterodactyl and persists it to repository configuration."""
    cfg = self.repo.load()
    if not cfg.panel_url or not cfg.api_key:
      raise ConfigurationError(
          "Pterodactyl Panel URL and API Key must be configured first."
      )

    idx = cfg.find_server_index(identifier)
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
    if self.runtime_state:
      if (
          server_id_override
          and old_sid
          and old_sid.strip().lower() != sid.strip().lower()
      ):
        self.runtime_state.rename_server_state(old_sid, sid)
      elif sid:
        self.runtime_state.get_server_state(sid)
    return res.name

  def update_server_toggle(
      self, identifier: Union[str, int], field: str, value: bool
  ):
    """Toggles and immediately persists a single boolean setting on a server."""
    try:
      asyncio.get_running_loop()
      return _LockableOperation(
          self._lock, self._execute_update_server_toggle, identifier, field, value
      )
    except RuntimeError:
      return self._execute_update_server_toggle(identifier, field, value)

  def _execute_update_server_toggle(
      self, identifier: Union[str, int], field: str, value: bool
  ) -> None:
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
    idx = cfg.find_server_index(identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))

    setattr(cfg.servers[idx], field, bool(value))
    self.repo.save(cfg)
    return cfg.servers[idx]

  async def toggle_server(
      self, identifier: Union[str, int], field: str, value: bool
  ) -> ServerModel:
    """Serialized asynchronous toggle server setting alias."""
    async with self._lock:
      return self._execute_update_server_toggle(identifier, field, value)

  async def save_single_server(
      self,
      identifier: Union[str, int],
      data: Union[SingleServerSaveRequest, dict],
  ) -> ServerModel:
    """Persists structured configuration changes for an individual server card."""
    async with self._lock:
      cfg = self.repo.load()
      idx = cfg.find_server_index(identifier)
      if idx is None:
        raise ServerNotFoundError(str(identifier))

      srv = cfg.servers[idx]
      old_server_id = srv.server_id

      if isinstance(data, SingleServerSaveRequest):
        fields = data.model_fields_set
        if "server_id" in fields and data.server_id.strip():
          srv.server_id = data.server_id.strip()
        elif not srv.server_id and data.server_id:
          srv.server_id = data.server_id.strip()

        if "app_id" in fields or data.app_id:
          srv.app_id = data.app_id.strip()

        if "manifest_path" in fields or data.manifest_path:
          srv.manifest_path = data.manifest_path.strip()

        if "query_port_offset" in fields or data.query_port_offset is not None:
          srv.query_port_offset = data.query_port_offset

        if "broadcast_command_template" in fields or data.broadcast_command_template:
          srv.broadcast_command_template = (
              data.broadcast_command_template.strip() or "say {message}"
          )
        name_input = data.name.strip() if "name" in fields else ""
      else:
        if "server_id" in data and str(data["server_id"]).strip():
          srv.server_id = str(data["server_id"]).strip()
        if "app_id" in data:
          srv.app_id = str(data["app_id"]).strip()
        if "manifest_path" in data:
          srv.manifest_path = str(data["manifest_path"]).strip()
        if "broadcast_command_template" in data:
          srv.broadcast_command_template = (
              str(data["broadcast_command_template"]).strip() or "say {message}"
          )

        found_offset = False
        for key in (
            "query_port_offset",
            "port_offset",
            "srv_port_offset",
            "srv_query_port_offset",
        ):
          if key in data:
            try:
              srv.query_port_offset = int(data[key])
            except (ValueError, TypeError):
              srv.query_port_offset = 0
            found_offset = True
            break

        if not found_offset:
          indexed_key = f"srv_port_offset_{idx}"
          if indexed_key in data:
            try:
              srv.query_port_offset = int(data[indexed_key])
            except (ValueError, TypeError):
              srv.query_port_offset = 0
          elif srv.server_id and f"srv_port_offset_{srv.server_id}" in data:
            try:
              srv.query_port_offset = int(data[f"srv_port_offset_{srv.server_id}"])
            except (ValueError, TypeError):
              srv.query_port_offset = 0

        name_input = str(data.get("name", "")).strip() if "name" in data else ""

      if name_input:
        srv.name = name_input

      self.repo.save(cfg)
      if self.runtime_state:
        if (
            old_server_id
            and old_server_id.strip().lower() != srv.server_id.strip().lower()
        ):
          self.runtime_state.rename_server_state(old_server_id, srv.server_id)
        elif srv.server_id:
          self.runtime_state.get_server_state(srv.server_id)
      return srv

  async def detect_server_details(self, server_id: str) -> DetectedServerDetails:
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

  async def search_steam_games(self, query: str) -> list[SteamSearchResult]:
    """Searches Steam catalog and dedicated servers by query."""
    return await self.steam.search_games(query)

