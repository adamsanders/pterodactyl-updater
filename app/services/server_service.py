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
from app.web.schemas import SettingsFormData

logger = logging.getLogger("updater.server_service")


class ServerService:

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      discord: NotificationGateway,
      preview_store: WebhookPreviewStore,
      simulator_store: BuildSimulatorStore,
      countdown: CountdownManagerProtocol,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.discord = discord
    self.preview_store = preview_store
    self.simulator_store = simulator_store
    self.countdown = countdown

  def save_settings(self, form_data: SettingsFormData) -> None:
    cfg = self.repo.load()
    cfg.panel_url = form_data.panel_url
    cfg.api_key = form_data.api_key
    cfg.check_interval = form_data.check_interval
    cfg.discord_webhook = form_data.discord_webhook
    cfg.test_mode = form_data.test_mode
    cfg.servers = form_data.servers
    self.repo.save(cfg)

  def add_server(self, form_data: SettingsFormData) -> None:
    self.save_settings(form_data)
    cfg = self.repo.load()
    cfg.servers.append(ServerModel())
    self.repo.save(cfg)

  def delete_server(self, index: int, form_data: SettingsFormData) -> None:
    self.save_settings(form_data)
    cfg = self.repo.load()
    if 0 <= index < len(cfg.servers):
      cfg.servers.pop(index)
      self.repo.save(cfg)

  async def rename_server(
      self, index: int, new_name: str, form_data: SettingsFormData
  ) -> bool:
    self.save_settings(form_data)
    cfg = self.repo.load()

    if not (0 <= index < len(cfg.servers)) or not new_name:
      return False

    target_server = cfg.servers[index]
    success, err = await self.ptero.rename_server(
        cfg.panel_url, cfg.api_key, target_server.server_id, new_name
    )

    if success:
      target_server.name = new_name
      target_server.last_status = "Renamed in Pterodactyl"
    else:
      target_server.last_status = f"Rename failed: {err}"

    self.repo.save(cfg)
    return success

  async def send_power_action(
        self, index: int, action: str
    ) -> tuple[bool, str | None]:
      valid_actions = {"start", "restart", "stop", "kill"}
      if action not in valid_actions:
        return False, f"Invalid power action '{action}'."

      cfg = self.repo.load()
      if not (0 <= index < len(cfg.servers)):
        return False, "Server index out of range."

      server = cfg.servers[index]
      if not cfg.panel_url or not cfg.api_key or not server.server_id:
        return False, "Server ID or Panel API Key configuration is incomplete."

      # Restart, stop, or kill cancels any pending update countdown
      if action in ("restart", "stop", "kill"):
        if self.countdown.is_running(server.server_id):
          logger.info(
              f"[{server.name}] Power action '{action}' triggered."
              " Cancelling active auto-restart countdown."
          )
          self.countdown.stop(server.server_id)
          server.last_status = f"Countdown cancelled ({action} requested)"
          self.repo.save(cfg)

      return await self.ptero.send_power_signal(
          panel_url=cfg.panel_url,
          api_key=cfg.api_key,
          server_id=server.server_id,
          signal=action,
      )

  async def test_webhook(self, index: int) -> None:
    cfg = self.repo.load()
    if not (0 <= index < len(cfg.servers)):
      return

    server = cfg.servers[index]
    embed = await self.steam.fetch_patchnotes(server.app_id)
    msg = f"🧪 **[TEST ALERT]** Testing webhook dispatch for **{server.name}**."

    if cfg.test_mode:
      self.preview_store.set_preview(
          WebhookPreview(
              server_name=server.name,
              message=msg,
              embed=embed,
              timestamp=datetime.now().strftime("%I:%M %p"),
          )
      )
      server.last_status = "Test simulated (Test Mode ON)"
    elif cfg.discord_webhook:
      await self.discord.send_notification(cfg.discord_webhook, msg, embed)
      server.last_status = "Test webhook dispatched to Discord"
    else:
      server.last_status = "Error: No Discord Webhook configured"

    self.repo.save(cfg)

  def simulate_build_update(
        self, server_index: int, new_build_id: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
      cfg = self.repo.load()
      if not cfg.test_mode:
        return False, "Test Mode is not enabled.", None
      if not (0 <= server_index < len(cfg.servers)):
        return False, "Server index out of range.", None

      server = cfg.servers[server_index]
      # Clear previous simulations so only this selected server is targeted
      self.simulator_store.clear_simulated_build()
      self.simulator_store.set_simulated_build(server.server_id, new_build_id)
      return True, None, server.server_id

  def toggle_test_mode(self, enabled: bool) -> bool:
      cfg = self.repo.load()
      cfg.test_mode = enabled
      if not enabled:
        self.simulator_store.clear_simulated_build()
        # Abort any countdowns initiated during simulation
        for srv in cfg.servers:
          if self.countdown.is_running(srv.server_id):
            self.countdown.stop(srv.server_id)
            srv.last_status = "Test mode disabled — countdown cancelled"
      self.repo.save(cfg)
      return enabled