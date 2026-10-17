import inspect
import logging
from typing import TYPE_CHECKING, List, Optional, Union

from app.core.exceptions import SimulationError
from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    OperationResult,
    PowerSignal,
    PowerState,
    SaveServerCommand,
    SaveSettingsCommand,
    ServerModel,
    ServerUpdateStatus,
    SteamSearchResult,
)
from app.core.protocols import (
    BuildSimulatorProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    NotificationGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
    UpdateOrchestratorProtocol,
    WebhookPreviewStoreProtocol,
)
from app.services.announcement_service import AnnouncementService
from app.services.server_config_service import ServerConfigService
from app.services.server_power_service import ServerPowerService

logger = logging.getLogger("updater.server_service")


class ServerService:
  """Facade composing ServerConfigService and ServerPowerService for unified server management."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: SteamGateway,
      simulator_store: BuildSimulatorProtocol,
      countdown: CountdownManagerProtocol,
      announcements: Optional[AnnouncementService] = None,
      discord: Optional[NotificationGateway] = None,
      preview_store: Optional[WebhookPreviewStoreProtocol] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      orchestrator: Optional[UpdateOrchestratorProtocol] = None,
      config_service: Optional[ServerConfigService] = None,
      power_service: Optional[ServerPowerService] = None,
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

    self.config_service = (
        config_service
        if config_service is not None
        else ServerConfigService(
            repository=repository,
            ptero=ptero,
            steam=steam,
            runtime_state=runtime_state,
            countdown_coordinator=(
                orchestrator.countdown_coordinator
                if orchestrator and hasattr(orchestrator, "countdown_coordinator")
                else None
            ),
            countdown=countdown,
            simulator_store=simulator_store,
        )
    )
    if (
        getattr(self.config_service, "countdown_coordinator", None) is None
        and orchestrator
        and hasattr(orchestrator, "countdown_coordinator")
    ):
      self.config_service.countdown_coordinator = (
          orchestrator.countdown_coordinator
      )
    if getattr(self.config_service, "countdown", None) is None:
      self.config_service.countdown = countdown
    if getattr(self.config_service, "simulator_store", None) is None:
      self.config_service.simulator_store = simulator_store
    if getattr(self.config_service, "runtime_state", None) is None:
      self.config_service.runtime_state = runtime_state


    self.power_service = (
        power_service
        if power_service is not None
        else ServerPowerService(
            repository=repository,
            ptero=ptero,
            countdown=countdown,
            orchestrator=orchestrator,
            runtime_state=runtime_state,
        )
    )

  @property
  def discord(self) -> Optional[NotificationGateway]:
    return self.announcements.discord

  @property
  def preview_store(self) -> Optional[WebhookPreviewStoreProtocol]:
    return self.announcements.preview_store

  def save_settings(self, settings: SaveSettingsCommand):
    return self.config_service.save_settings(settings)

  def add_server(self, settings: SaveSettingsCommand):
    return self.config_service.add_server(settings)

  def find_server_index(
      self,
      servers_or_identifier: Union[List[ServerModel], AppConfigModel, str, int],
      identifier: Optional[Union[str, int]] = None,
  ) -> Optional[int]:
    return self.config_service.find_server_index(servers_or_identifier, identifier)

  def delete_server(
      self,
      identifier: Union[str, int],
      settings: Optional[SaveSettingsCommand] = None,
  ):
    return self.config_service.delete_server(identifier, settings)

  async def rename_server(
      self,
      identifier: Union[str, int],
      new_name: str,
      settings: SaveSettingsCommand,
  ) -> bool:
    return await self.config_service.rename_server(identifier, new_name, settings)

  async def send_power_action(
      self, identifier: Union[str, int], action: Union[PowerSignal, str]
  ) -> OperationResult:
    return await self.power_service.send_power_action(identifier, action)

  async def get_power_state(
      self, identifier: Union[str, int]
  ) -> PowerState:
    return await self.power_service.get_power_state(identifier)

  async def execute_graceful_restart(
      self, identifier: Union[str, int]
  ) -> OperationResult:
    return await self.power_service.execute_graceful_restart(identifier)

  async def test_webhook(self, identifier: Union[str, int]) -> str:
    cfg = self.repo.load()
    idx = self.find_server_index(cfg.servers, identifier)
    if idx is None:
      return "Server not found"

    server = cfg.servers[idx]
    _, status_msg = await self.announcements.send_test_alert(server)
    object.__setattr__(server, "_ephemeral_last_status", status_msg)
    if self.runtime_state:
      self.runtime_state.update_server_state(
          server.server_id, last_status=status_msg
      )
    self.repo.save(cfg)
    return status_msg

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
    self.simulator_store.clear_simulated_build()
    self.simulator_store.set_simulated_build(server.server_id, new_build_id)
    return True, None, server.server_id

  async def trigger_simulated_build(
      self, identifier: Union[str, int], new_build_id: str
  ) -> str:
    success, err, target_server_id = self.simulate_build_update(
        identifier, new_build_id
    )
    if not success:
      raise SimulationError(err or "Simulation failed")

    if self.orchestrator and target_server_id:
      self.orchestrator.clear_restarted_build(target_server_id)
      await self.orchestrator.run_update_check(target_server_id=target_server_id)

    return target_server_id or str(identifier)

  def clear_simulated_build(
      self, identifier: Optional[Union[str, int]] = None
  ) -> Optional[str]:
    cfg = self.repo.load()
    target_id: Optional[str] = None
    if identifier is not None and str(identifier).strip():
      idx = self.find_server_index(cfg.servers, identifier)
      if idx is not None:
        target_id = cfg.servers[idx].server_id
      else:
        target_id = str(identifier).strip()
      self.simulator_store.clear_simulated_build(target_id)
    else:
      self.simulator_store.clear_simulated_build()
    return target_id

  async def toggle_test_mode(self, enabled: bool) -> bool:
    async with self.config_service.lock:
      cfg = self.repo.load()
      cfg.test_mode = enabled
      if not enabled:
        self.simulator_store.clear_simulated_build()
        for srv in cfg.servers:
          if self.countdown.is_running(srv.server_id):
            self.countdown.stop(srv.server_id)
            object.__setattr__(srv, "_ephemeral_last_status", ServerUpdateStatus.IDLE)
            if self.runtime_state:
              self.runtime_state.update_server_state(
                  srv.server_id,
                  last_status=ServerUpdateStatus.IDLE,
              )
      if hasattr(self.config_service, "_persist_config"):
        await self.config_service._persist_config(cfg)
      else:
        self.repo.save(cfg)
    if self.orchestrator:
      self.orchestrator.clear_restarted_build()
      if not enabled:
        await self.orchestrator.run_update_check()
    return enabled

  async def toggle_ssl_verify(self, enabled: bool) -> bool:
    res = self.config_service.toggle_ssl_verify(enabled)
    if inspect.isawaitable(res):
      return await res
    return res

  async def trigger_immediate_check(self) -> None:
    self.ptero.invalidate_power_cache()
    if self.orchestrator:
      await self.orchestrator.run_update_check()

  async def lookup_server_name(self, server_id: str) -> str:
    return await self.config_service.lookup_server_name(server_id)

  async def sync_server_name(
      self,
      identifier: Union[str, int],
      server_id_override: Optional[str] = None,
  ) -> str:
    return await self.config_service.sync_server_name(identifier, server_id_override)

  def update_server_toggle(
      self, identifier: Union[str, int], field: str, value: bool
  ):
    return self.config_service.update_server_toggle(identifier, field, value)

  async def toggle_server(
      self, identifier: Union[str, int], field: str, value: bool
  ) -> ServerModel:
    return await self.config_service.toggle_server(identifier, field, value)

  async def save_single_server(
      self,
      identifier: Union[str, int],
      data: Union[SaveServerCommand, dict],
  ) -> ServerModel:
    return await self.config_service.save_single_server(identifier, data)

  async def detect_server_details(
      self, server_id: str
  ) -> DetectedServerDetails:
    return await self.config_service.detect_server_details(server_id)

  async def search_steam_games(
      self, query: str
  ) -> list[SteamSearchResult]:
    return await self.config_service.search_steam_games(query)