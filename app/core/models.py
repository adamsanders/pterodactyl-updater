from typing import List, NamedTuple, Optional
from pydantic import BaseModel, Field


class ServerAllocation(NamedTuple):
  """Network allocation containing host IP and connection port."""
  ip: Optional[str] = None
  port: Optional[int] = None


class PlayerMetrics(NamedTuple):
  """Real-time player capacity telemetry queried via Steam A2S protocol."""
  current: Optional[int] = None
  max: Optional[int] = None


class LocalBuildResult(NamedTuple):
  """Result of reading game server build ID from local disk manifest."""
  build_id: Optional[str] = None
  error: Optional[str] = None


class ServerNameResult(NamedTuple):
  """Result of fetching server name from Pterodactyl API."""
  name: Optional[str] = None
  error: Optional[str] = None


class OperationResult(NamedTuple):
  """General result for remote state mutations and commands."""
  success: bool
  error: Optional[str] = None


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
  app_id: str = "896660"
  manifest_path: str = "steamapps/appmanifest_896660.acf"
  auto_restart: bool = True
  discord_alerts: bool = True
  warn_ingame_countdown: bool = True
  warn_discord_countdown: bool = True
  current_build: str = Field(default="Unknown", exclude=True)
  latest_build: str = Field(default="Unknown", exclude=True)
  last_status: str = Field(default="Idle", exclude=True)


class AppConfigModel(BaseModel):
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  last_check: str = Field(default="Never", exclude=True)
  last_status: str = Field(default="Idle", exclude=True)
  servers: List[ServerModel] = Field(default_factory=list)


class SettingsUpdateDTO(BaseModel):
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  servers: List[ServerModel] = Field(default_factory=list)


class ServerStatusDTO(BaseModel):
    idx: int
    server_id: str
    name: str
    power_state: str
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