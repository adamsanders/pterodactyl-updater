import asyncio
from typing import Any, Optional, Protocol, Tuple, Union, runtime_checkable
from app.core.models import (
    AppConfigModel,
    AppRuntimeState,
    DetectedServerDetails,
    LocalBuildResult,
    OperationResult,
    PlayerMetrics,
    PowerSignal,
    PowerState,
    ServerAllocation,
    ServerModel,
    ServerNameResult,
    ServerRuntimeState,
    ServerStatusDTO,
    ServerUpdateStatus,
    SteamPatchNotes,
    SteamSearchResult,
)



class RuntimeStateStoreProtocol(Protocol):

  def get_global_state(self) -> AppRuntimeState:
    ...

  def update_global_state(
      self,
      last_check: Optional[str] = None,
      last_status: Optional[Union[ServerUpdateStatus, str]] = None,
  ) -> AppRuntimeState:
    ...

  def get_server_state(self, server_id: str) -> ServerRuntimeState:
    ...

  def update_server_state(
      self,
      server_id: str,
      current_build: Optional[str] = None,
      latest_build: Optional[str] = None,
      last_status: Optional[Union[ServerUpdateStatus, str]] = None,
  ) -> ServerRuntimeState:
    ...

  def remove_server_state(self, server_id: str) -> None:
    ...

  def delete_server_state(self, server_id: str) -> None:
    ...

  def rename_server_state(
      self, old_server_id: str, new_server_id: str
  ) -> Optional[ServerRuntimeState]:
    ...

  def get_all_server_states(self) -> dict[str, ServerRuntimeState]:
    ...

  def reconcile_with_servers(self, servers: list[ServerModel]) -> None:
    ...

  def seed_from_config(self, config: AppConfigModel) -> None:
    ...

  def clear(self) -> None:
    ...


@runtime_checkable
class ConfigRepositoryGateway(Protocol):

  def load(self) -> AppConfigModel:
    ...

  def save(self, config: AppConfigModel) -> None:
    ...

  async def async_save(self, config: AppConfigModel) -> None:
    ...


# Backward compatibility alias
ConfigRepositoryProtocol = ConfigRepositoryGateway


class CallTrackerProtocol(Protocol):

  def record(
      self,
      endpoint: str,
      method: str = "GET",
      status: str = "200",
      duration_ms: float = 0.0,
      details: str = "",
  ) -> None:
    ...

  def get_telemetry_snapshot(self) -> dict:
    ...

  def clear(self) -> None:
    ...


@runtime_checkable
class PublicIpGateway(Protocol):

  async def get_external_ip(self) -> Optional[str]:
    ...


@runtime_checkable
class PterodactylPowerGateway(Protocol):

  async def get_power_state(
      self, panel_url: str, api_key: str, server_id: str
  ) -> PowerState:
    ...

  def consume_startup_transition(self, server_id: str) -> bool:
    ...

  def invalidate_power_cache(self, server_id: Optional[str] = None) -> None:
    ...

  async def trigger_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> OperationResult:
    ...

  async def send_power_signal(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
      signal: PowerSignal | str,
  ) -> OperationResult:
    ...

  async def execute_graceful_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    ...


@runtime_checkable
class PterodactylInspectionGateway(Protocol):

  async def get_server_name(
      self, panel_url: str, api_key: str, server_id: str
  ) -> ServerNameResult:
    ...

  async def get_server_allocation(
      self, panel_url: str, api_key: str, server_id: str
  ) -> ServerAllocation:
    ...

  async def get_local_build(
      self, panel_url: str, api_key: str, server_id: str, manifest_path: str
  ) -> LocalBuildResult:
    ...


@runtime_checkable
class PterodactylManagementGateway(Protocol):

  async def send_command(
      self, panel_url: str, api_key: str, server_id: str, command: str
  ) -> None:
    ...

  async def rename_server(
      self, panel_url: str, api_key: str, server_id: str, new_name: str
  ) -> OperationResult:
    ...

  async def detect_server_details(
      self, panel_url: str, api_key: str, server_id: str
  ) -> DetectedServerDetails:
    ...


@runtime_checkable
class PterodactylGateway(
    PublicIpGateway,
    PterodactylPowerGateway,
    PterodactylInspectionGateway,
    PterodactylManagementGateway,
    Protocol,
):
  pass


@runtime_checkable
class SteamGateway(Protocol):

  async def get_latest_build(
      self, app_id: str, server_id: Optional[str] = None
  ) -> Optional[str]:
    ...

  async def fetch_patchnotes(
      self, appid: int | str
  ) -> Optional[Union[SteamPatchNotes, dict]]:
    ...

  async def search_games(self, query: str) -> list[SteamSearchResult]:
    ...


@runtime_checkable
class PlayerQueryGateway(Protocol):

  async def get_player_count(
      self, host: str, port: int
  ) -> PlayerMetrics:
    ...


# Backward compatibility alias
A2SGateway = PlayerQueryGateway


@runtime_checkable
class NotificationGateway(Protocol):

  def create_patchnotes_embed(
      self, notes: Union[SteamPatchNotes, dict]
  ) -> dict[str, Any]:
    ...

  async def send_notification(
      self,
      webhook_url: str,
      message: Optional[str] = None,
      embed: Optional[Union[dict, SteamPatchNotes]] = None,
  ) -> None:
    ...


@runtime_checkable
class CountdownGateway(Protocol):

  def start(
      self,
      server_id: str,
      duration_seconds: int = 900,
      task: Optional[asyncio.Task] = None,
  ) -> None:
    ...

  def attach_task(self, server_id: str, task: asyncio.Task) -> None:
    ...

  def stop(self, server_id: str) -> None:
    ...

  def stop_all(self) -> list[asyncio.Task]:
    ...

  def active_server_ids(self) -> list[str]:
    ...

  def get_target(self, server_id: str) -> float:
    ...

  def is_running(self, server_id: str) -> bool:
    ...

  def get_remaining(self, server_id: str) -> int:
    ...


# Backward compatibility alias
CountdownManagerProtocol = CountdownGateway


@runtime_checkable
class PowerTrackerGateway(Protocol):

  def register_signal(
      self, server_id: str, signal: Union[PowerSignal, str]
  ) -> PowerState:
    ...

  def get_valid_cache(self, server_id: str) -> Optional[PowerState]:
    ...

  def filter_state(
      self, server_id: str, raw_state: Optional[Union[PowerState, str]]
  ) -> PowerState:
    ...

  def invalidate(self, server_id: Optional[str] = None) -> None:
    ...

  def pop_just_started(self, server_id: str) -> bool:
    ...


# Backward compatibility alias
PowerStateTrackerProtocol = PowerTrackerGateway


@runtime_checkable
class BuildSimulatorProtocol(Protocol):
  """Protocol for managing simulated SteamCMD build IDs during test mode."""

  def set_simulated_build(self, server_id: str, build_id: str) -> None:
    ...

  def get_simulated_build(self, server_id: str) -> Optional[str]:
    ...

  def has_simulated_build(self, server_id: str) -> bool:
    ...

  def clear_simulated_build(self, server_id: Optional[str] = None) -> None:
    ...


@runtime_checkable
class WebhookPreviewStoreProtocol(Protocol):
  """Protocol for managing in-memory webhook preview payloads."""

  def set_preview(self, preview: Any) -> None:
    ...

  def get_preview(self) -> Optional[Any]:
    ...

  def clear(self) -> None:
    ...

  def consume_preview(self) -> Optional[Any]:
    ...


@runtime_checkable
class StatusAggregationGateway(Protocol):

  async def get_single_server_status(
      self,
      cfg: AppConfigModel,
      ext_ip: Optional[str],
      idx: int,
      srv: ServerModel,
  ) -> Optional[ServerStatusDTO]:
    ...

  async def get_status_snapshot(self) -> dict[str, Any]:
    ...


@runtime_checkable
class CountdownCoordinatorGateway(Protocol):

  def cancel_countdown(
      self,
      server_id: str,
      reason: str = "",
      server_name: Optional[str] = None,
  ) -> None:
    ...

  def cancel_all_countdowns(
      self, reason: str = "Application shutdown"
  ) -> list[asyncio.Task]:
    ...

  def is_countdown_running(self, server_id: str) -> bool:
    ...

  def start_countdown(self, server: ServerModel) -> asyncio.Task:
    ...


# Backward compatibility alias
CountdownCoordinatorProtocol = CountdownCoordinatorGateway


class UpdateOrchestratorProtocol(Protocol):

  @property
  def loop_task(self) -> Optional[asyncio.Task]:
    ...

  def start_loop(self) -> asyncio.Task:
    ...

  def stop_loop(self) -> None:
    ...

  def clear_restarted_build(self, server_id: Optional[str] = None) -> None:
    ...

  def cancel_countdown(self, server_id: str, reason: str = "") -> None:
    ...

  def cancel_all_countdowns(
      self, reason: str = "Application shutdown"
  ) -> list[asyncio.Task]:
    ...

  async def run_update_check(
      self, target_server_id: Optional[str] = None
  ) -> None:
    ...