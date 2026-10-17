import logging
from typing import List, Optional, Union

from app.core.exceptions import ConfigurationError, ServerNotFoundError
from app.core.models import AppConfigModel, OperationResult, PowerSignal, PowerState, ServerModel
from app.core.protocols import (
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylPowerGateway,
    RuntimeStateStoreProtocol,
    UpdateOrchestratorProtocol,
)

logger = logging.getLogger("updater.server_power")


class ServerPowerService:
  """Dedicated service handling power signal dispatch, power state inspection, and graceful restarts."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylPowerGateway,
      countdown: CountdownManagerProtocol,
      orchestrator: Optional[UpdateOrchestratorProtocol] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.countdown = countdown
    self.orchestrator = orchestrator
    self.runtime_state = runtime_state

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

  async def get_power_state(
      self, identifier: Union[str, int]
  ) -> PowerState:
    """Queries current power state of the server from Pterodactyl gateway."""
    cfg = self.repo.load()
    idx = cfg.find_server_index(identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))
    srv = cfg.servers[idx]
    if not cfg.panel_url or not cfg.api_key or not srv.server_id:
      return PowerState.UNKNOWN
    return await self.ptero.get_power_state(cfg.panel_url, cfg.api_key, srv.server_id)

  async def send_power_action(
      self, identifier: Union[str, int], action: Union[PowerSignal, str]
  ) -> OperationResult:
    """Dispatches power action (start, stop, restart, kill) to the specified server."""
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
    idx = cfg.find_server_index(identifier)
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
        object.__setattr__(server, "_ephemeral_last_status", status_msg)
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

  async def execute_graceful_restart(
      self, identifier: Union[str, int]
  ) -> OperationResult:
    """Executes a graceful restart or falls back according to Pterodactyl adapter restart policy."""
    cfg = self.repo.load()
    idx = cfg.find_server_index(identifier)
    if idx is None:
      raise ServerNotFoundError(str(identifier))
    server = cfg.servers[idx]
    if not cfg.panel_url or not cfg.api_key or not server.server_id:
      raise ConfigurationError("Incomplete configuration for restart")
    if self.orchestrator:
      self.orchestrator.clear_restarted_build(server.server_id)
    return await self.ptero.trigger_restart(cfg.panel_url, cfg.api_key, server.server_id)
