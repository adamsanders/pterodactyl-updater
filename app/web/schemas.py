from typing import List
from app.core.models import ServerModel, SettingsUpdateDTO
from starlette.datastructures import FormData


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

    servers: List[ServerModel] = []
    for idx, srv in enumerate(current_servers):
      sid = srv.server_id.strip() if srv.server_id else ""

      def get_field(prefix: str, default: str = "") -> str:
        if sid and f"{prefix}_{sid}" in form:
          val = form.get(f"{prefix}_{sid}")
          return str(val) if val is not None else default
        val = form.get(f"{prefix}_{idx}")
        return str(val) if val is not None else default

      def get_srv_bool(prefix: str) -> bool:
        if sid and f"{prefix}_{sid}" in form:
          return get_bool(f"{prefix}_{sid}")
        return get_bool(f"{prefix}_{idx}")

      def get_int(prefix: str, default: int = 0) -> int:
        raw_val = None
        if sid and f"{prefix}_{sid}" in form:
          raw_val = form.get(f"{prefix}_{sid}")
        elif f"{prefix}_{idx}" in form:
          raw_val = form.get(f"{prefix}_{idx}")
        if raw_val is not None and str(raw_val).strip() != "":
          try:
            return int(str(raw_val).strip())
          except (ValueError, TypeError):
            return default
        return default

      port_offset = srv.query_port_offset
      for pfx in ("srv_port_offset", "srv_query_port_offset", "srv_queryportoffset", "query_port_offset"):
        if (sid and f"{pfx}_{sid}" in form) or (f"{pfx}_{idx}" in form):
          port_offset = get_int(pfx, 0)
          break

      srv_name = get_field("srv_name", srv.name) or srv.name
      servers.append(
          ServerModel(
              name=srv_name,
              server_id=get_field("srv_id", srv.server_id),
              app_id=get_field("srv_appid", srv.app_id),
              manifest_path=get_field("srv_manifest", srv.manifest_path),
              auto_restart=get_srv_bool("srv_autorestart"),
              discord_alerts=get_srv_bool("srv_discord"),
              warn_ingame_countdown=get_srv_bool("srv_warningame"),
              warn_discord_countdown=get_srv_bool("srv_warndiscord"),
              query_port_offset=port_offset,
              current_build=srv.current_build,
              latest_build=srv.latest_build,
              last_status=srv.last_status,
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