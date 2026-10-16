from typing import List, Optional, Union
from pydantic import BaseModel, Field
from app.core.models import ServerModel, SettingsUpdateDTO, SingleServerSaveRequest
from starlette.datastructures import FormData


class SimulateBuildRequest(BaseModel):
  """Typed JSON request body for triggering a simulated build update."""
  build_id: str
  server_id: Optional[Union[str, int]] = None
  server_idx: Optional[int] = 0


class SyncNameRequest(BaseModel):
  """Typed JSON request body for synchronizing server name from Pterodactyl Panel."""
  server_id: str = ""


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
              current_build=srv.current_build if srv else "?",
              latest_build=srv.latest_build if srv else "?",
              last_status=srv.last_status if srv else "",
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