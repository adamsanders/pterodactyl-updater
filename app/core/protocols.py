import asyncio
from typing import Optional, Protocol, Tuple
from app.core.models import (
    AppConfigModel,
    AppRuntimeState,
    LocalBuildResult,
    OperationResult,
    PlayerMetrics,
    ServerAllocation,
    ServerModel,
    ServerNameResult,
    ServerRuntimeState,
)


class RuntimeStateStoreProtocol(Protocol):

  def get_global_state(self) -> AppRuntimeState:
    ...

  def update_global_state(
      self,
      last_check: Optional[str] = None,
      last_status: Optional[str] = None,
  ) -> AppRuntimeState:
    ...

  def get_server_state(self, server_id: str) -> ServerRuntimeState:
    ...

  def update_server_state(
      self,
      server_id: str,
      current_build: Optional[str] = None,
      latest_build: Optional[str] = None,
      last_status: Optional[str] = None,
  ) -> ServerRuntimeState:
    ...

  def get_all_server_states(self) -> dict[str, ServerRuntimeState]:
    ...

  def seed_from_config(self, config: AppConfigModel) -> None:
    ...

  def clear(self) -> None:
    ...


class ConfigRepositoryProtocol(Protocol):

  def load(self) -> AppConfigModel:
    ...

  def save(self, config: AppConfigModel) -> None:
    ...


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


class PterodactylGateway(Protocol):

  async def get_server_name(
      self, panel_url: str, api_key: str, server_id: str
  ) -> ServerNameResult:
    ...

  async def get_power_state(
      self, panel_url: str, api_key: str, server_id: str
  ) -> str:
    ...

  def consume_startup_transition(self, server_id: str) -> bool:
    ...

  def invalidate_power_cache(self, server_id: Optional[str] = None) -> None:
    ...

  async def get_external_ip(self) -> Optional[str]:
    ...

  async def get_server_allocation(
      self, panel_url: str, api_key: str, server_id: str
  ) -> ServerAllocation:
    ...

  async def get_local_build(
      self, panel_url: str, api_key: str, server_id: str, manifest_path: str
  ) -> LocalBuildResult:
    ...

  async def send_command(
      self, panel_url: str, api_key: str, server_id: str, command: str
  ) -> None:
    ...

  async def trigger_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> OperationResult:
    ...

  async def send_power_signal(
      self, panel_url: str, api_key: str, server_id: str, signal: str
  ) -> OperationResult:
    ...

  async def rename_server(
      self, panel_url: str, api_key: str, server_id: str, new_name: str
  ) -> OperationResult:
    ...

  async def execute_graceful_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    ...

  async def detect_server_details(
      self, panel_url: str, api_key: str, server_id: str
  ) -> dict:
    ...


class SteamGateway(Protocol):

  async def get_latest_build(
      self, app_id: str, server_id: Optional[str] = None
  ) -> Optional[str]:
    ...

  async def fetch_patchnotes(self, appid: int | str) -> Optional[dict]:
    ...

  async def search_games(self, query: str) -> list[dict]:
    ...


class A2SGateway(Protocol):

  async def get_player_count(
      self, host: str, port: int
  ) -> PlayerMetrics:
    ...


class NotificationGateway(Protocol):

  async def send_notification(
      self,
      webhook_url: str,
      message: Optional[str] = None,
      embed: Optional[dict] = None,
  ) -> None:
    ...


class CountdownManagerProtocol(Protocol):

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

  def get_target(self, server_id: str) -> float:
    ...

  def is_running(self, server_id: str) -> bool:
    ...

  def get_remaining(self, server_id: str) -> int:
    ...


class UpdateOrchestratorProtocol(Protocol):

  def clear_restarted_build(self, server_id: Optional[str] = None) -> None:
    ...

  async def run_update_check(
      self, target_server_id: Optional[str] = None
  ) -> None:
    ...