from typing import List, Optional
from pydantic import BaseModel, Field


class ServerModel(BaseModel):
  name: str = "New Server"
  server_id: str = ""
  app_id: str = "896660"
  manifest_path: str = "steamapps/appmanifest_896660.acf"
  auto_restart: bool = True
  discord_alerts: bool = True
  warn_ingame_countdown: bool = True
  warn_discord_countdown: bool = True
  current_build: str = "Unknown"
  latest_build: str = "Unknown"
  last_status: str = "Idle"


class AppConfigModel(BaseModel):
  panel_url: str = ""
  api_key: str = ""
  check_interval: int = Field(default=15, ge=1, le=1440)
  discord_webhook: str = ""
  test_mode: bool = False
  last_check: str = "Never"
  last_status: str = "Idle"
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