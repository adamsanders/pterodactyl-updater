from enum import Enum
import re
from typing import Any, List, NamedTuple, Optional, Union
from app.core.catalogs import IGNORED_STEAM_APPIDS
from app.core.exceptions import (
    ConfigurationError,
    DomainError,
    InvalidPowerActionError,
    PterodactylApiError,
    ServerNotFoundError,
)
from pydantic import BaseModel, Field, field_validator, model_validator

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        """Fallback StrEnum for Python < 3.11 with str value representation."""
        def __str__(self) -> str:
            return str(self.value)


class PowerState(StrEnum):
    RUNNING = "running"
    OFFLINE = "offline"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"

    @classmethod
    def from_str(cls, value: Optional[Union["PowerState", str]]) -> "PowerState":
        if isinstance(value, cls):
            return value
        val_str = (value or "unknown").lower().strip()
        if val_str in ("offline", "stopped"):
            return cls.OFFLINE
        elif val_str == "running":
            return cls.RUNNING
        elif val_str == "starting":
            return cls.STARTING
        elif val_str == "stopping":
            return cls.STOPPING
        return cls.UNKNOWN


class PowerSignal(StrEnum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    KILL = "kill"

    @classmethod
    def from_str(cls, value: Optional[Union["PowerSignal", str]]) -> "PowerSignal":
        if isinstance(value, cls):
            return value
        val_str = (value or "").lower().strip()
        for member in cls:
            if member.value == val_str:
                return member
        raise ValueError(f"Invalid power signal '{value}'")



class ServerAllocation(NamedTuple):
  """Network allocation containing host IP and connection port."""
  ip: Optional[str] = None
  port: Optional[int] = None


class PlayerMetrics(NamedTuple):
  """Real-time player capacity telemetry queried via Steam A2S protocol."""
  current: Optional[int] = None
  max: Optional[int] = None


def _parse_status_code_from_error(err_msg: str, default: int = 400) -> int:
  m = re.search(r"Panel HTTP (\d+)", err_msg)
  if m:
    try:
      return int(m.group(1))
    except (ValueError, TypeError):
      pass
  return default


class LocalBuildResult(NamedTuple):
  """Result of reading game server build ID from local disk manifest."""
  build_id: Optional[str] = None
  error: Optional[str] = None
  status_code: Optional[int] = None
  error_type: Optional[str] = None

  def __iter__(self):
    yield self.build_id
    yield self.error

  def raise_if_failed(
      self,
      exc_cls: Optional[type[DomainError]] = None,
      status_code: Optional[int] = None,
      server_id: Optional[str] = None,
  ) -> str:
    if self.error or not self.build_id:
      err_msg = self.error or "Manifest build ID could not be resolved"
      target_cls = exc_cls or PterodactylApiError
      effective_sc = status_code if status_code is not None else self.status_code
      if effective_sc is None:
        effective_sc = _parse_status_code_from_error(err_msg, default=400)
      if issubclass(target_cls, PterodactylApiError):
        raise target_cls(err_msg, status_code=effective_sc or 400, server_id=server_id)
      raise target_cls(err_msg)
    return self.build_id


class ServerNameResult(NamedTuple):
  """Result of fetching server name from Pterodactyl API."""
  name: Optional[str] = None
  error: Optional[str] = None
  status_code: Optional[int] = None
  error_type: Optional[str] = None

  def __iter__(self):
    yield self.name
    yield self.error

  def raise_if_failed(
      self,
      exc_cls: Optional[type[DomainError]] = None,
      status_code: Optional[int] = None,
      server_id: Optional[str] = None,
  ) -> str:
    if self.error or not self.name:
      err_msg = self.error or "Server name could not be resolved"
      target_cls = exc_cls or PterodactylApiError
      effective_sc = status_code if status_code is not None else self.status_code
      if effective_sc is None:
        effective_sc = _parse_status_code_from_error(err_msg, default=400)
      if issubclass(target_cls, PterodactylApiError):
        raise target_cls(err_msg, status_code=effective_sc or 400, server_id=server_id)
      raise target_cls(err_msg)
    return self.name


class OperationResult(NamedTuple):
  """General result for remote state mutations and commands."""
  success: bool
  error: Optional[str] = None
  status_code: Optional[int] = None
  error_type: Optional[str] = None

  def __iter__(self):
    yield self.success
    yield self.error

  def __bool__(self) -> bool:
    return self.success

  def raise_if_failed(
      self,
      exc_cls: Optional[type[DomainError]] = None,
      status_code: Optional[int] = None,
      server_id: Optional[str] = None,
  ) -> "OperationResult":
    """Raises a DomainError if the operation did not succeed."""
    if not self.success:
      err_msg = self.error or "Operation failed"
      effective_sc = status_code if status_code is not None else self.status_code
      if exc_cls is not None:
        if issubclass(exc_cls, PterodactylApiError):
          sc = effective_sc
          if sc is None:
            sc = _parse_status_code_from_error(err_msg, default=400)
          raise exc_cls(err_msg, status_code=sc or 400, server_id=server_id)
        raise exc_cls(err_msg)

      # Automatic classification
      if self.error_type == "InvalidPowerAction" or "Invalid power action" in err_msg:
        action = err_msg.split("'")[1] if "'" in err_msg else err_msg
        raise InvalidPowerActionError(action, status_code=effective_sc or 400)
      elif (
          self.error_type in ("ServerNotFound", "NotFound")
          or "out of range" in err_msg
          or "not found" in err_msg.lower()
      ):
        raise ServerNotFoundError(server_id or "unknown", status_code=effective_sc or 404)
      elif self.error_type == "ConfigurationError":
        raise ConfigurationError(err_msg, status_code=effective_sc or 400)
      else:
        sc = effective_sc
        if sc is None:
          sc = _parse_status_code_from_error(err_msg, default=400)
        raise PterodactylApiError(err_msg, status_code=sc or 400, server_id=server_id)
    return self


class ServerRuntimeState(BaseModel):
  """Ephemeral runtime state for a single managed game server."""
  server_id: str = ""
  current_build: str = "Unknown"
  latest_build: str = "Unknown"
  last_status: str = "Idle"


class AppRuntimeState(BaseModel):
  """Ephemeral runtime state for the application and background updater loop."""
  last_check: str = "Never"
  last_status: str = "Idle"


class ServerModel(BaseModel):
  name: str = "New Server"
  server_id: str = ""
  app_id: str = ""
  manifest_path: str = ""
  auto_restart: bool = False
  discord_alerts: bool = False
  warn_ingame_countdown: bool = False
  warn_discord_countdown: bool = False
  query_port_offset: int = 0
  current_build: str = Field(default="Unknown", exclude=True)
  latest_build: str = Field(default="Unknown", exclude=True)
  last_status: str = Field(default="Idle", exclude=True)

  @field_validator("query_port_offset", mode="before")
  @classmethod
  def parse_query_port_offset(cls, v: Any) -> int:
    if v is None or v == "":
      return 0
    try:
      return int(v)
    except (ValueError, TypeError):
      return 0

  @model_validator(mode="after")
  def default_manifest_from_appid(self) -> "ServerModel":
    # 1. Purge known redistributable tool App IDs (e.g. 1007 Steamworks SDK)
    if self.app_id in IGNORED_STEAM_APPIDS:
      self.app_id = ""
    if self.manifest_path and any(
        f"appmanifest_{bad}.acf" in self.manifest_path.lower()
        for bad in IGNORED_STEAM_APPIDS
    ):
      self.manifest_path = ""

    # 2. Re-derive standard manifest path if valid app_id exists and path is empty
    if not self.manifest_path and self.app_id:
      self.manifest_path = f"steamapps/appmanifest_{self.app_id}.acf"
    return self


class AppConfigModel(BaseModel):
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  ssl_verify: bool = False
  last_check: str = Field(default="Never", exclude=True)
  last_status: str = Field(default="Idle", exclude=True)
  servers: List[ServerModel] = Field(default_factory=list)


class SettingsUpdateDTO(BaseModel):
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  ssl_verify: bool = False
  servers: List[ServerModel] = Field(default_factory=list)


class ServerStatusDTO(BaseModel):
    idx: int
    server_id: str
    name: str
    power_state: PowerState
    current_build: str
    latest_build: str
    last_status: str
    target_timestamp: float
    remaining_seconds: int
    is_updating: bool
    # Network & Query Telemetry
    external_ip: Optional[str] = None
    internal_ip: Optional[str] = None
    port: Optional[int] = None
    query_port: Optional[int] = None
    player_count: Optional[int] = None
    max_players: Optional[int] = None


class WebhookPreview(BaseModel):
  server_name: str
  message: str
  embed: Optional[dict] = None
  timestamp: str