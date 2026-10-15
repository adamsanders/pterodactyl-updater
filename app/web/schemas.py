from typing import List
from app.core.models import ServerModel, SettingsUpdateDTO
from starlette.datastructures import FormData


class SettingsFormData:
  """Web presentation parser translating HTML form data into domain SettingsUpdateDTO."""

  @classmethod
  async def from_form(
      cls, form: FormData, current_servers: List[ServerModel]
  ) -> SettingsUpdateDTO:
    servers: List[ServerModel] = []
    for idx, srv in enumerate(current_servers):
      servers.append(
          ServerModel(
              name=srv.name,
              server_id=str(form.get(f"srv_id_{idx}", srv.server_id)),
              app_id=str(form.get(f"srv_appid_{idx}", srv.app_id)),
              manifest_path=str(form.get(f"srv_manifest_{idx}", srv.manifest_path)),
              auto_restart=form.get(f"srv_autorestart_{idx}") == "true",
              discord_alerts=form.get(f"srv_discord_{idx}") == "true",
              warn_ingame_countdown=form.get(f"srv_warningame_{idx}") == "true",
              warn_discord_countdown=form.get(f"srv_warndiscord_{idx}")
              == "true",
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
        servers=servers,
    )