from typing import List
from app.core.models import ServerModel
from starlette.datastructures import FormData


class SettingsFormData:

  def __init__(
      self,
      panel_url: str,
      api_key: str,
      check_interval: int,
      discord_webhook: str,
      test_mode: bool,
      servers: List[ServerModel],
  ):
    self.panel_url = panel_url
    self.api_key = api_key
    self.check_interval = check_interval
    self.discord_webhook = discord_webhook
    self.test_mode = test_mode
    self.servers = servers

  @classmethod
  async def from_form(
      cls, form: FormData, current_servers: List[ServerModel]
  ) -> "SettingsFormData":
    servers: List[ServerModel] = []
    for idx, srv in enumerate(current_servers):
      servers.append(
          ServerModel(
              name=srv.name,
              server_id=form.get(f"srv_id_{idx}", srv.server_id),
              app_id=form.get(f"srv_appid_{idx}", srv.app_id),
              manifest_path=form.get(f"srv_manifest_{idx}", srv.manifest_path),
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

    return cls(
        panel_url=form.get("panel_url", ""),
        api_key=form.get("api_key", ""),
        check_interval=int(form.get("check_interval", 15)),
        discord_webhook=form.get("discord_webhook", ""),
        test_mode=form.get("test_mode") == "true",
        servers=servers,
    )