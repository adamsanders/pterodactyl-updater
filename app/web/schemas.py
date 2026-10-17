from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field
from app.core.models import AppConfigModel, ServerModel, ServerRuntimeState
from starlette.datastructures import FormData


class SingleServerSaveRequest(BaseModel):
  """Typed JSON request body for saving an individual server card."""
  name: str = ""
  server_id: str = ""
  app_id: str = ""
  manifest_path: str = ""
  query_port_offset: int = 0
  broadcast_command_template: str = "say {message}"


class SettingsUpdateDTO(BaseModel):
  """Presentation DTO encapsulating global settings form updates."""
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  ssl_verify: bool = False
  servers: List[ServerModel] = Field(default_factory=list)


class WebhookPreview(BaseModel):
  """Presentation DTO for simulated or pending Discord notification webhooks."""
  server_name: str
  message: str
  embed: Optional[dict] = None
  timestamp: str


class SimulateBuildRequest(BaseModel):
  """Typed JSON request body for triggering a simulated build update."""
  build_id: str
  server_id: Optional[Union[str, int]] = None
  server_idx: Optional[int] = 0


class SyncNameRequest(BaseModel):
  """Typed JSON request body for synchronizing server name from Pterodactyl Panel."""
  server_id: str = ""


class LookupNameResponse(BaseModel):
  """Typed response model for server name lookup."""
  model_config = ConfigDict(extra="allow")

  name: Optional[str] = None
  success: bool = True
  status: str = "ok"


class PowerActionResponse(BaseModel):
  """Typed response model for server power actions."""
  model_config = ConfigDict(extra="allow")

  status: str
  server_id: str
  action: str
  effective_state: Optional[str] = None
  server_idx: Optional[int] = None


class ServerCardViewModel(BaseModel):
  """Presentation ViewModel encapsulating individual server configuration and runtime telemetry."""
  model_config = ConfigDict(extra="ignore")

  card_index: int = 0
  server_id: str = ""
  name: str = ""
  app_id: str = ""
  manifest_path: str = ""
  query_port_offset: int = 0
  broadcast_command_template: str = "say {message}"
  auto_restart: bool = False
  discord_alerts: bool = False
  warn_ingame_countdown: bool = False
  warn_discord_countdown: bool = False
  current_build: str = "Unknown"
  latest_build: str = "Unknown"
  status: str = ""
  countdown_remaining: int = 0
  countdown_target: int = 0

  @property
  def last_status(self) -> str:
    return self.status

  @property
  def idx(self) -> int:
    return self.card_index

  def __getitem__(self, item: str) -> Any:
    if hasattr(self, item):
      return getattr(self, item)
    raise KeyError(item)

  def get(self, item: str, default: Any = None) -> Any:
    if hasattr(self, item):
      val = getattr(self, item)
      return val if val is not None else default
    return default

  def __contains__(self, item: str) -> bool:
    return item in self.__class__.model_fields or hasattr(self, item)

  def __iter__(self):
    return iter(self.__class__.model_fields.keys())

  def keys(self):
    return self.__class__.model_fields.keys()

  def values(self):
    return [getattr(self, k) for k in self.__class__.model_fields.keys()]

  def items(self):
    return [(k, getattr(self, k)) for k in self.__class__.model_fields.keys()]

  @classmethod
  def from_domain(
      cls,
      server: ServerModel,
      card_index: int = 0,
      runtime_state: Optional[ServerRuntimeState] = None,
      countdown_remaining: int = 0,
      countdown_target: int = 0,
  ) -> "ServerCardViewModel":
    current_build = "Unknown"
    latest_build = "Unknown"
    status = ""

    if runtime_state:
      current_build = runtime_state.current_build or "Unknown"
      latest_build = runtime_state.latest_build or "Unknown"
      if runtime_state.last_status and str(runtime_state.last_status) != "Idle":
        status = str(runtime_state.last_status)
    else:
      ephem_cur = getattr(server, "_ephemeral_current_build", None) or getattr(server, "current_build", None)
      if ephem_cur:
        current_build = str(ephem_cur)
      ephem_lat = getattr(server, "_ephemeral_latest_build", None) or getattr(server, "latest_build", None)
      if ephem_lat:
        latest_build = str(ephem_lat)
      ephem_stat = getattr(server, "_ephemeral_last_status", None) or getattr(server, "last_status", None)
      if ephem_stat and str(ephem_stat) != "Idle":
        status = str(ephem_stat)

    if current_build == "Unknown":
      ephem_cur = getattr(server, "_ephemeral_current_build", None) or getattr(server, "current_build", None)
      if ephem_cur and str(ephem_cur) != "Unknown":
        current_build = str(ephem_cur)
    if latest_build == "Unknown":
      ephem_lat = getattr(server, "_ephemeral_latest_build", None) or getattr(server, "latest_build", None)
      if ephem_lat and str(ephem_lat) != "Unknown":
        latest_build = str(ephem_lat)

    return cls(
        card_index=card_index,
        server_id=server.server_id,
        name=server.name,
        app_id=server.app_id,
        manifest_path=server.manifest_path,
        query_port_offset=server.query_port_offset,
        broadcast_command_template=server.broadcast_command_template,
        auto_restart=server.auto_restart,
        discord_alerts=server.discord_alerts,
        warn_ingame_countdown=server.warn_ingame_countdown,
        warn_discord_countdown=server.warn_discord_countdown,
        current_build=current_build,
        latest_build=latest_build,
        status=status,
        countdown_remaining=int(countdown_remaining),
        countdown_target=int(countdown_target),
    )


class DashboardViewModel(BaseModel):
  """Presentation ViewModel encapsulating global dashboard settings, servers, and telemetry."""
  model_config = ConfigDict(extra="ignore")

  panel_url: str = ""
  api_key: str = ""
  check_interval: int = 15
  discord_webhook: str = ""
  test_mode: bool = False
  ssl_verify: bool = False
  last_check: str = "Never"
  last_status: str = "Idle"
  servers: list[ServerCardViewModel] = Field(default_factory=list)
  app_version: str = ""
  commit_code: str = ""
  preview: Optional[Union[WebhookPreview, dict]] = None

  @property
  def version(self) -> str:
    return self.app_version

  def __getitem__(self, item: str) -> Any:
    if hasattr(self, item):
      return getattr(self, item)
    raise KeyError(item)

  def get(self, item: str, default: Any = None) -> Any:
    if hasattr(self, item):
      val = getattr(self, item)
      return val if val is not None else default
    return default

  def __contains__(self, item: str) -> bool:
    return item in self.__class__.model_fields or hasattr(self, item)

  def __iter__(self):
    return iter(self.__class__.model_fields.keys())

  def keys(self):
    return self.__class__.model_fields.keys()

  def values(self):
    return [getattr(self, k) for k in self.__class__.model_fields.keys()]

  def items(self):
    return [(k, getattr(self, k)) for k in self.__class__.model_fields.keys()]

  @classmethod
  def from_domain(
      cls,
      config: AppConfigModel,
      runtime_states: Optional[dict[str, ServerRuntimeState]] = None,
      countdown: Optional[Any] = None,
      last_check: Optional[str] = None,
      last_status: Optional[str] = None,
      app_version: str = "",
      commit_code: str = "",
      preview: Optional[Union[WebhookPreview, dict]] = None,
  ) -> "DashboardViewModel":
    effective_last_check = last_check or getattr(config, "last_check", "Never")
    effective_last_status = last_status or getattr(config, "last_status", "Idle")
    card_vms = []
    for idx, srv in enumerate(config.servers):
      sid = srv.server_id
      st = None
      if runtime_states and sid:
        st = (
            runtime_states.get(sid)
            or runtime_states.get(sid.lower())
            or runtime_states.get(sid.strip().lower())
        )
      rem = 0
      target_ts = 0
      if countdown and sid:
        try:
          rem = int(countdown.get_remaining(sid) or 0)
        except Exception:
          rem = 0
        try:
          target_ts = int(countdown.get_target(sid) or 0)
        except Exception:
          target_ts = 0

      card_vm = ServerCardViewModel.from_domain(
          server=srv,
          card_index=idx,
          runtime_state=st,
          countdown_remaining=rem,
          countdown_target=target_ts,
      )
      card_vms.append(card_vm)

    return cls(
        panel_url=config.panel_url,
        api_key=config.api_key,
        check_interval=config.check_interval,
        discord_webhook=config.discord_webhook,
        test_mode=config.test_mode,
        ssl_verify=config.ssl_verify,
        last_check=effective_last_check,
        last_status=effective_last_status,
        servers=card_vms,
        app_version=app_version,
        commit_code=commit_code,
        preview=preview,
    )


class SettingsFormData:
  """Web presentation parser translating HTML form data into domain SettingsUpdateDTO."""

  @classmethod
  async def from_form(
      cls, form: FormData, current_servers: List[ServerModel]
  ) -> SettingsUpdateDTO:
    def get_bool(key: str, default: bool = False) -> bool:
      val = form.get(key)
      if val is None:
        return default
      if isinstance(val, bool):
        return val
      return str(val).strip().lower() in ("true", "1", "on", "yes")

    server_map_by_id = {
        s.server_id.strip(): s for s in current_servers if s.server_id
    }

    srv_keys: List[str] = []
    for k in form.keys():
      if k.startswith("srv_id_"):
        key_suffix = k[len("srv_id_"):]
        if key_suffix not in srv_keys:
          srv_keys.append(key_suffix)

    servers: List[ServerModel] = []
    keys_to_iterate = srv_keys if srv_keys else [str(i) for i in range(len(current_servers))]

    for idx, key in enumerate(keys_to_iterate):
      srv = None
      if key in server_map_by_id:
        srv = server_map_by_id[key]
      elif key.isdigit() and int(key) < len(current_servers):
        srv = current_servers[int(key)]
      else:
        sub_id = str(form.get(f"srv_id_{key}", "")).strip()
        if sub_id and sub_id in server_map_by_id:
          srv = server_map_by_id[sub_id]

      sid = srv.server_id.strip() if (srv and srv.server_id) else ""
      sub_id = str(form.get(f"srv_id_{key}", "")).strip()
      effective_id = sub_id or sid

      def get_field(prefix: str, default: str = "") -> str:
        if f"{prefix}_{key}" in form:
          val = form.get(f"{prefix}_{key}")
          return str(val) if val is not None else default
        for identifier in (effective_id, sid):
          if identifier and f"{prefix}_{identifier}" in form:
            val = form.get(f"{prefix}_{identifier}")
            return str(val) if val is not None else default
        if key.isdigit() and f"{prefix}_{int(key)}" in form:
          val = form.get(f"{prefix}_{int(key)}")
          return str(val) if val is not None else default
        return default

      def get_srv_bool(prefix: str) -> bool:
        if f"{prefix}_{key}" in form:
          return get_bool(f"{prefix}_{key}")
        for identifier in (effective_id, sid):
          if identifier and f"{prefix}_{identifier}" in form:
            return get_bool(f"{prefix}_{identifier}")
        if key.isdigit() and f"{prefix}_{int(key)}" in form:
          return get_bool(f"{prefix}_{int(key)}")
        return False

      def get_int(prefix: str, default: int = 0) -> int:
        raw_val = None
        if f"{prefix}_{key}" in form:
          raw_val = form.get(f"{prefix}_{key}")
        if raw_val is None:
          for identifier in (effective_id, sid):
            if identifier and f"{prefix}_{identifier}" in form:
              raw_val = form.get(f"{prefix}_{identifier}")
              break
        if raw_val is None and key.isdigit() and f"{prefix}_{int(key)}" in form:
          raw_val = form.get(f"{prefix}_{int(key)}")

        if raw_val is not None and str(raw_val).strip() != "":
          try:
            return int(str(raw_val).strip())
          except (ValueError, TypeError):
            return default
        return default

      port_offset = srv.query_port_offset if srv else 0
      for pfx in ("srv_port_offset", "srv_query_port_offset", "srv_queryportoffset", "query_port_offset"):
        if (f"{pfx}_{key}" in form) or (effective_id and f"{pfx}_{effective_id}" in form) or (sid and f"{pfx}_{sid}" in form):
          port_offset = get_int(pfx, 0)
          break

      default_name = srv.name if srv else "New Server"
      srv_name = get_field("srv_name", default_name) or default_name
      default_cmd = getattr(srv, "broadcast_command_template", "say {message}") if srv else "say {message}"
      srv_broadcast_cmd = (
          get_field("srv_broadcast_cmd", default_cmd)
          or get_field("srv_broadcast_command_template", default_cmd)
          or "say {message}"
      )

      servers.append(
          ServerModel(
              name=srv_name,
              server_id=effective_id,
              app_id=get_field("srv_appid", srv.app_id if srv else ""),
              manifest_path=get_field("srv_manifest", srv.manifest_path if srv else ""),
              auto_restart=get_srv_bool("srv_autorestart"),
              discord_alerts=get_srv_bool("srv_discord"),
              warn_ingame_countdown=get_srv_bool("srv_warningame"),
              warn_discord_countdown=get_srv_bool("srv_warndiscord"),
              query_port_offset=port_offset,
              broadcast_command_template=srv_broadcast_cmd,
              current_build=getattr(srv, "_ephemeral_current_build", "?") if srv else "?",
              latest_build=getattr(srv, "_ephemeral_latest_build", "?") if srv else "?",
              last_status=getattr(srv, "_ephemeral_last_status", "") if srv else "",
          )
      )

    return SettingsUpdateDTO(
        panel_url=str(form.get("panel_url", "")),
        api_key=str(form.get("api_key", "")),
        check_interval=int(form.get("check_interval", 15)),
        discord_webhook=str(form.get("discord_webhook", "")),
        test_mode=form.get("test_mode") == "true",
        ssl_verify=get_bool("ssl_verify"),
        servers=servers,
    )