from datetime import datetime
import logging
from typing import Optional
from app.core.models import ServerModel, SettingsUpdateDTO, WebhookPreview
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    NotificationGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
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
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.simulator_store = simulator_store
    self.countdown = countdown
    self.runtime_state = runtime_state
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
    cfg.servers = list(settings.servers)
    self.repo.save(cfg)

  def add_server(self, settings: SettingsUpdateDTO) -> None:
    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.servers = list(settings.servers)
    cfg.servers.append(ServerModel())
    self.repo.save(cfg)

  def delete_server(self, index: int, settings: SettingsUpdateDTO) -> None:
    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.servers = list(settings.servers)
    if 0 <= index < len(cfg.servers):
      cfg.servers.pop(index)
    self.repo.save(cfg)

  async def rename_server(
      self, index: int, new_name: str, settings: SettingsUpdateDTO
  ) -> bool:
    if not (0 <= index < len(settings.servers)) or not new_name:
      return False

    target_server = settings.servers[index]
    success, err = await self.ptero.rename_server(
        settings.panel_url, settings.api_key, target_server.server_id, new_name
    )

    cfg = self.repo.load()
    cfg.panel_url = settings.panel_url
    cfg.api_key = settings.api_key
    cfg.check_interval = settings.check_interval
    cfg.discord_webhook = settings.discord_webhook
    cfg.test_mode = settings.test_mode
    cfg.servers = list(settings.servers)

    if 0 <= index < len(cfg.servers):
      if success:
        cfg.servers[index].name = new_name
        cfg.servers[index].last_status = "Renamed in Pterodactyl"
        if self.runtime_state:
          self.runtime_state.update_server_state(
              target_server.server_id, last_status="Renamed in Pterodactyl"
          )
      else:
        cfg.servers[index].last_status = f"Rename failed: {err}"
        if self.runtime_state:
          self.runtime_state.update_server_state(
              target_server.server_id, last_status=f"Rename failed: {err}"
          )

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
          status_msg = f"Countdown cancelled ({action} requested)"
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
          signal=action,
      )

  async def test_webhook(self, index: int) -> None:
    cfg = self.repo.load()
    if not (0 <= index < len(cfg.servers)):
      return

    server = cfg.servers[index]
    _, status_msg = await self.announcements.send_test_alert(server)
    server.last_status = status_msg
    if self.runtime_state:
      self.runtime_state.update_server_state(
          server.server_id, last_status=status_msg
      )
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
            if self.runtime_state:
              self.runtime_state.update_server_state(
                  srv.server_id,
                  last_status="Test mode disabled — countdown cancelled",
              )
      self.repo.save(cfg)
      return enabled