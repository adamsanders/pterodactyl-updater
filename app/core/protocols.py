import asyncio
from typing import Optional, Protocol, Tuple
from app.core.models import AppConfigModel, ServerModel


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
  ) -> Tuple[Optional[str], Optional[str]]:
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
  ) -> Tuple[Optional[str], Optional[int]]:
    ...

  async def get_local_build(
      self, panel_url: str, api_key: str, server_id: str, manifest_path: str
  ) -> Tuple[Optional[str], Optional[str]]:
    ...

  async def send_command(
      self, panel_url: str, api_key: str, server_id: str, command: str
  ) -> None:
    ...

  async def trigger_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    ...

  async def send_power_signal(
      self, panel_url: str, api_key: str, server_id: str, signal: str
  ) -> Tuple[bool, Optional[str]]:
    ...

  async def rename_server(
      self, panel_url: str, api_key: str, server_id: str, new_name: str
  ) -> Tuple[bool, Optional[str]]:
    ...

  async def execute_graceful_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    ...


class SteamGateway(Protocol):

  async def get_latest_build(
      self, app_id: str, server_id: Optional[str] = None
  ) -> Optional[str]:
    ...

  async def fetch_patchnotes(self, appid: int | str) -> Optional[dict]:
    ...


class A2SGateway(Protocol):

  async def get_player_count(
      self, host: str, port: int
  ) -> Tuple[Optional[int], Optional[int]]:
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