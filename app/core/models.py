from enum import Enum
from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional, Union
from app.core.catalogs import IGNORED_STEAM_APPIDS
from app.core.exceptions import (
    ConfigurationError,
    ConflictError,
    DomainError,
    InvalidPowerActionError,
    NotFoundError,
    PterodactylApiError,
    ServerNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

if TYPE_CHECKING:
  from app.web.schemas import (  # noqa: F401
      SettingsUpdateDTO,
      SingleServerSaveRequest,
      WebhookPreview,
  )

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


class ServerUpdateStatus(StrEnum):
    UP_TO_DATE = "Up to date"
    UPDATE_AVAILABLE = "Update Available"
    COUNTDOWN_ACTIVE = "Update Available (Countdown Active)"
    RESTART_DISPATCHED = "Restart dispatched — waiting for build update"
    IDLE = "Idle"
    ERROR = "Error"

    @classmethod
    def from_str(cls, value: Optional[Union["ServerUpdateStatus", str]]) -> "ServerUpdateStatus":
        if isinstance(value, cls):
            return value
        val_str = (value or "").strip().lower()
        if not val_str:
            return cls.IDLE
        for member in cls:
            if member.value.lower() == val_str:
                return member
        # Fallback mappings for partial or legacy status strings
        if "cancel" in val_str:
            return cls.IDLE
        elif "countdown" in val_str:
            return cls.COUNTDOWN_ACTIVE
        elif "restart" in val_str or "waiting" in val_str:
            return cls.RESTART_DISPATCHED
        elif "update available" in val_str:
            return cls.UPDATE_AVAILABLE
        elif "up to date" in val_str:
            return cls.UP_TO_DATE
        elif "error" in val_str or "fail" in val_str:
            return cls.ERROR
        return cls.IDLE



class ServerAllocation(NamedTuple):
  """Network allocation containing host IP and connection port."""
  ip: Optional[str] = None
  port: Optional[int] = None


class PlayerMetrics(NamedTuple):
  """Real-time player capacity telemetry queried via Steam A2S protocol."""
  current: Optional[int] = None
  max: Optional[int] = None


def _raise_domain_error(
    err_msg: str,
    status_code: Optional[int],
    error_type: Optional[str],
    exc_cls: Optional[type[DomainError]] = None,
    server_id: Optional[str] = None,
) -> None:
  """Centralized structured error dispatcher eliminating regex string scraping across domain results."""
  effective_sc = status_code
  if exc_cls is not None:
    if issubclass(exc_cls, PterodactylApiError):
      raise exc_cls(err_msg, status_code=effective_sc or 400, server_id=server_id)
    if hasattr(exc_cls, "status_code"):
      try:
        raise exc_cls(err_msg, status_code=effective_sc or 400, server_id=server_id)
      except TypeError:
        pass
    raise exc_cls(err_msg)

  # 5xx Server Errors or explicit 5xx overrides always map to PterodactylApiError
  if effective_sc is not None and effective_sc >= 500:
    raise PterodactylApiError(err_msg, status_code=effective_sc, server_id=server_id)

  # Automatic classification relying directly on error_type and status_code
  if error_type == "InvalidPowerAction":
    raise InvalidPowerActionError(err_msg, status_code=effective_sc or 400)
  if error_type in ("ServerNotFound", "NotFound") or effective_sc == 404:
    if server_id:
      raise ServerNotFoundError(server_id, status_code=effective_sc or 404)
    raise NotFoundError(err_msg, status_code=effective_sc or 404, server_id=server_id)
  if error_type in ("Unauthorized", "Forbidden") or effective_sc in (401, 403):
    raise UnauthorizedError(err_msg, status_code=effective_sc or 401, server_id=server_id)
  if error_type == "Conflict" or effective_sc == 409:
    raise ConflictError(err_msg, status_code=effective_sc or 409, server_id=server_id)
  if error_type == "ValidationError" or effective_sc == 422:
    raise ValidationError(err_msg, status_code=effective_sc or 422, server_id=server_id)
  if error_type == "ConfigurationError":
    raise ConfigurationError(err_msg, status_code=effective_sc or 400)

  # Safe fallback to generic domain exception
  raise PterodactylApiError(err_msg, status_code=effective_sc or 400, server_id=server_id)


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
      effective_sc = status_code if status_code is not None else self.status_code
      _raise_domain_error(
          err_msg=err_msg,
          status_code=effective_sc,
          error_type=self.error_type,
          exc_cls=exc_cls,
          server_id=server_id,
      )
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
      effective_sc = status_code if status_code is not None else self.status_code
      _raise_domain_error(
          err_msg=err_msg,
          status_code=effective_sc,
          error_type=self.error_type,
          exc_cls=exc_cls,
          server_id=server_id,
      )
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
      _raise_domain_error(
          err_msg=err_msg,
          status_code=effective_sc,
          error_type=self.error_type,
          exc_cls=exc_cls,
          server_id=server_id,
      )
    return self


class SteamPatchNotes(BaseModel):
  """Pure domain DTO encapsulating Steam community announcement metadata."""
  title: str
  content: str
  url: str
  image_url: Optional[str] = None
  posted_at: Optional[str] = None


class ServerRuntimeState(BaseModel):
  """Ephemeral runtime state for a single managed game server."""
  server_id: str = ""
  current_build: str = "Unknown"
  latest_build: str = "Unknown"
  last_status: Union[ServerUpdateStatus, str] = ServerUpdateStatus.IDLE


class AppRuntimeState(BaseModel):
  """Ephemeral runtime state for the application and background updater loop."""
  last_check: str = "Never"
  last_status: Union[ServerUpdateStatus, str] = ServerUpdateStatus.IDLE


class ServerModel(BaseModel):
  model_config = ConfigDict(extra="ignore")

  name: str = "New Server"
  server_id: str = ""
  app_id: str = ""
  manifest_path: str = ""
  auto_restart: bool = False
  discord_alerts: bool = False
  warn_ingame_countdown: bool = False
  warn_discord_countdown: bool = False
  query_port_offset: int = 0
  broadcast_command_template: str = "say {message}"

  def __init__(self, **data: Any):
    cur = data.pop("current_build", None)
    lat = data.pop("latest_build", None)
    st = data.pop("last_status", None)
    super().__init__(**data)
    if cur is not None:
      self._ephemeral_current_build = str(cur)
    if lat is not None:
      self._ephemeral_latest_build = str(lat)
    if st is not None:
      self._ephemeral_last_status = str(st)

  @property
  def current_build(self) -> str:
    import warnings
    warnings.warn(
        "ServerModel.current_build is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(self, "_ephemeral_current_build", "Unknown")

  @current_build.setter
  def current_build(self, val: str) -> None:
    import warnings
    warnings.warn(
        "Mutating ServerModel.current_build is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    self._ephemeral_current_build = str(val)

  @property
  def latest_build(self) -> str:
    import warnings
    warnings.warn(
        "ServerModel.latest_build is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(self, "_ephemeral_latest_build", "Unknown")

  @latest_build.setter
  def latest_build(self, val: str) -> None:
    import warnings
    warnings.warn(
        "Mutating ServerModel.latest_build is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    self._ephemeral_latest_build = str(val)

  @property
  def last_status(self) -> str:
    import warnings
    warnings.warn(
        "ServerModel.last_status is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(self, "_ephemeral_last_status", ServerUpdateStatus.IDLE)

  @last_status.setter
  def last_status(self, val: str) -> None:
    import warnings
    warnings.warn(
        "Mutating ServerModel.last_status is deprecated. Ephemeral operational state is tracked by RuntimeStateStore.",
        DeprecationWarning,
        stacklevel=2,
    )
    self._ephemeral_last_status = str(val)

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
  model_config = ConfigDict(extra="ignore")

  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  ssl_verify: bool = False
  servers: List[ServerModel] = Field(default_factory=list)

  _last_check: str = PrivateAttr(default="Never")
  _last_status: str = PrivateAttr(default=ServerUpdateStatus.IDLE)

  def __init__(self, **data: Any):
    lc = data.pop("last_check", None)
    ls = data.pop("last_status", None)
    super().__init__(**data)
    if lc is not None:
      self._last_check = str(lc)
    if ls is not None:
      self._last_status = str(ls)

  @property
  def last_check(self) -> str:
    return self._last_check

  @last_check.setter
  def last_check(self, val: str) -> None:
    self._last_check = str(val)

  @property
  def last_status(self) -> str:
    return self._last_status

  @last_status.setter
  def last_status(self, val: str) -> None:
    self._last_status = str(val)

  def find_server_index(self, identifier: Union[int, str]) -> Optional[int]:
    """Finds server index in the server collection by server_id or legacy numeric index."""
    if identifier is None or isinstance(identifier, bool):
      return None

    ident_str = str(identifier).strip()
    if not ident_str:
      return None

    ident_lower = ident_str.lower()
    # 1. Match by server_id (case-insensitive)
    for idx, srv in enumerate(self.servers):
      if srv.server_id and srv.server_id.strip().lower() == ident_lower:
        return idx

    # 2. Match by legacy numeric index if identifier is numeric
    try:
      numeric_idx = int(identifier)
      if 0 <= numeric_idx < len(self.servers):
        return numeric_idx
    except (ValueError, TypeError):
      pass

    return None




class ServerStatusDTO(BaseModel):
    idx: int
    server_id: str
    name: str
    power_state: PowerState
    current_build: str
    latest_build: str
    last_status: Union[ServerUpdateStatus, str]
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




class DetectedServerDetails(BaseModel):
  """Strongly-typed detection output for Pterodactyl server details."""
  name: Optional[str] = None
  app_id: Optional[str] = None
  manifest_path: Optional[str] = None
  detected: bool = False
  error: Optional[str] = None

  model_config = ConfigDict(populate_by_name=True)

  def __getitem__(self, item: str) -> Any:
    if hasattr(self, item):
      return getattr(self, item)
    raise KeyError(item)

  def get(self, item: str, default: Any = None) -> Any:
    if hasattr(self, item):
      val = getattr(self, item)
      return val if val is not None else default
    return default

  def __contains__(self, item: str) -> bool:
    return hasattr(self, item)


class SteamSearchResult(BaseModel):
  """Strongly-typed Steam search result model supporting dictionary access."""
  app_id: str
  name: str
  type: Optional[str] = None
  icon_url: Optional[str] = None
  banner_url: Optional[str] = None

  model_config = ConfigDict(populate_by_name=True)

  def __init__(self, **data: Any):
    if "appid" in data and "app_id" not in data:
      data["app_id"] = str(data["appid"])
    elif "app_id" in data:
      data["app_id"] = str(data["app_id"])
    super().__init__(**data)

  @property
  def appid(self) -> str:
    return self.app_id

  def __getitem__(self, item: str) -> Any:
    if item == "appid":
      return self.app_id
    if hasattr(self, item):
      return getattr(self, item)
    raise KeyError(item)

  def get(self, item: str, default: Any = None) -> Any:
    if item == "appid":
      return self.app_id
    if hasattr(self, item):
      val = getattr(self, item)
      return val if val is not None else default
    return default

  def __contains__(self, item: str) -> bool:
    if item == "appid":
      return True
    return hasattr(self, item)

  def __eq__(self, other: Any) -> bool:
    if isinstance(other, dict):
      other_id = other.get("app_id") or other.get("appid")
      return str(self.app_id) == str(other_id) and self.name == other.get("name")
    return super().__eq__(other)


class PowerTrackerEntry(BaseModel):
  """Strongly-typed power tracker internal state entry."""
  raw_state: PowerState = PowerState.UNKNOWN
  is_transitional: bool = False
  effective_state: PowerState = PowerState.UNKNOWN
  last_changed: float = 0.0
  stable_since: float = 0.0
  smoothed_state: PowerState = PowerState.UNKNOWN
  cached_state: PowerState = PowerState.UNKNOWN
  cache_expires: float = 0.0
  starting_since: float = 0.0
  startup_grace_until: float = 0.0
  stopping_since: float = 0.0
  stopped_during_start: bool = False
  restart_lockout_until: float = 0.0
  consecutive_offline: int = 0
  just_started: bool = False

  model_config = ConfigDict(arbitrary_types_allowed=True)

  def __getitem__(self, item: str) -> Any:
    if hasattr(self, item):
      return getattr(self, item)
    raise KeyError(item)

  def __setitem__(self, key: str, value: Any) -> None:
    setattr(self, key, value)

  def get(self, item: str, default: Any = None) -> Any:
    if hasattr(self, item):
      val = getattr(self, item)
      return val if val is not None else default
    return default

  def __contains__(self, item: str) -> bool:
    return hasattr(self, item)


# Backward-compatible forwarding re-exports for Presentation/Web DTOs
# (Relocated to app.web.schemas in Milestone 8 / v1.25.0)
def __getattr__(name: str) -> Any:
  if name in ("SettingsUpdateDTO", "SingleServerSaveRequest", "WebhookPreview"):
    import warnings
    warnings.warn(
        f"{name} has been relocated to app.web.schemas as part of domain purification. "
        f"Importing {name} from app.core.models is deprecated and will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
    import app.web.schemas as _schemas
    return getattr(_schemas, name)
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
  return sorted(list(globals().keys()) + ["SettingsUpdateDTO", "SingleServerSaveRequest", "WebhookPreview"])
