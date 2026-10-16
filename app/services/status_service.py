import asyncio
import logging
import time
from typing import Any, Callable, Optional

from app.core.catalogs import resolve_query_port
from app.core.config import APP_VERSION, COMMIT_CODE, TIMING_CONFIG
from app.core.models import (
    AppConfigModel,
    PowerState,
    ServerModel,
    ServerStatusDTO,
    ServerUpdateStatus,
)
from app.core.protocols import (
    A2SGateway,
    CallTrackerProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PowerTrackerGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
)
from app.services.preview_store import WebhookPreviewStore

logger = logging.getLogger("updater.status_service")

__all__ = ["StatusAggregationService", "resolve_query_port"]


class StatusAggregationService:
  """Aggregates multi-server fleet telemetry, power states, countdowns, and webhooks."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      countdown: CountdownManagerProtocol,
      preview_store: WebhookPreviewStore,
      orchestrator: Optional[Any] = None,
      a2s: Optional[A2SGateway] = None,
      call_tracker: Optional[CallTrackerProtocol] = None,
      markdown_formatter: Optional[Callable[[str], Any]] = None,
      runtime_state: Optional[RuntimeStateStoreProtocol] = None,
      power_tracker: Optional[PowerTrackerGateway] = None,
      telemetry_cache_ttl: float = 3.0,
  ):
    self.repository = repository
    self.ptero = ptero
    self.countdown = countdown
    self.preview_store = preview_store
    self.orchestrator = orchestrator
    self.a2s = a2s
    self.call_tracker = call_tracker
    self.markdown_formatter = markdown_formatter
    self.runtime_state = runtime_state
    self.power_tracker = power_tracker
    self.telemetry_cache_ttl = telemetry_cache_ttl
    self._telemetry_cache: dict[str, dict[str, Any]] = {}
    self._ext_ip_cache: tuple[Optional[str], float] = (None, 0.0)

  def invalidate_cache(self, server_id: Optional[str] = None) -> None:
    """Invalidates cached telemetry for a single server or entire fleet."""
    if server_id:
      self._telemetry_cache.pop(server_id, None)
    else:
      self._telemetry_cache.clear()

  async def get_single_server_status(
      self,
      cfg: AppConfigModel,
      ext_ip: Optional[str],
      idx: int,
      srv: ServerModel,
  ) -> ServerStatusDTO:
    """Pure query: reads telemetry, allocation, and power state for an individual game server with short-TTL caching."""
    now = time.time()
    sid = srv.server_id
    cached_telem = self._telemetry_cache.get(sid) if sid else None

    # Check real-time power tracker cache if available for instant power transitions
    tracker_power = None
    if self.power_tracker and sid:
      cand = self.power_tracker.get_valid_cache(sid)
      if isinstance(cand, (PowerState, str)):
        tracker_power = PowerState.from_str(cand)

    # Check whether cached telemetry is valid
    if cached_telem and cached_telem.get("expires", 0.0) > now:
      power = tracker_power if tracker_power is not None else cached_telem["power"]
      internal_ip = cached_telem["internal_ip"]
      game_port = cached_telem["port"]
      query_port = cached_telem["query_port"]
      if power == PowerState.RUNNING:
        player_count = cached_telem["player_count"]
        max_players = cached_telem["max_players"]
      else:
        player_count, max_players = None, None
    else:
      # Retrieve power state using power tracker cache or gateway
      power = tracker_power if tracker_power is not None else PowerState.UNKNOWN
      if power == PowerState.UNKNOWN and cfg.panel_url and cfg.api_key and sid:
        raw_power = await self.ptero.get_power_state(
            cfg.panel_url, cfg.api_key, sid
        )
        power = PowerState.from_str(raw_power)

      internal_ip, game_port = None, None
      if cfg.panel_url and cfg.api_key and sid:
        internal_ip, game_port = await self.ptero.get_server_allocation(
            cfg.panel_url, cfg.api_key, sid
        )

      query_port = (
          resolve_query_port(srv.app_id, game_port, srv.query_port_offset)
          if game_port
          else None
      )

      player_count, max_players = None, None
      if self.a2s and power == PowerState.RUNNING and ext_ip and query_port:
        player_count, max_players = await self.a2s.get_player_count(
            ext_ip, query_port
        )

      if sid:
        self._telemetry_cache[sid] = {
            "power": power,
            "internal_ip": internal_ip,
            "port": game_port,
            "query_port": query_port,
            "player_count": player_count,
            "max_players": max_players,
            "expires": now + self.telemetry_cache_ttl,
        }

    # Non-blocking in-memory reads for runtime build status and countdown
    target_ts = self.countdown.get_target(sid) if sid else 0.0
    rem = self.countdown.get_remaining(sid) if sid else 0

    if self.runtime_state and sid:
      st = self.runtime_state.get_server_state(sid)
      cur_build = st.current_build
      lat_build = st.latest_build
      srv_status = st.last_status
    elif srv:
      cur_build = srv.current_build
      lat_build = srv.latest_build
      srv_status = srv.last_status
    else:
      cur_build = "Unknown"
      lat_build = "Unknown"
      srv_status = ServerUpdateStatus.IDLE

    is_upd = (power != PowerState.OFFLINE) and (
        (self.countdown.is_running(sid) if sid else False)
        or (
            cur_build != lat_build
            and cur_build not in ("Unknown", "?")
            and lat_build not in ("Unknown", "?")
        )
    )

    return ServerStatusDTO(
        idx=idx,
        server_id=srv.server_id,
        name=srv.name,
        power_state=power,
        current_build=cur_build,
        latest_build=lat_build,
        last_status=srv_status,
        target_timestamp=target_ts,
        remaining_seconds=rem,
        is_updating=is_upd,
        external_ip=ext_ip,
        internal_ip=internal_ip,
        port=game_port,
        query_port=query_port,
        player_count=player_count,
        max_players=max_players,
    )

  async def get_status_snapshot(self) -> dict[str, Any]:
    """Collates full fleet telemetry as a pure, side-effect free read query with cached telemetry."""
    cfg = self.repository.load()

    if self.call_tracker:
      self.call_tracker.record(
          endpoint="Internal: /api/status Poll",
          method="GET",
          status="200",
          duration_ms=0.5,
          details="Client dashboard live sync",
      )

    now = time.time()
    cached_ip, ip_expires = self._ext_ip_cache
    if cached_ip and ip_expires > now:
      ext_ip = cached_ip
    else:
      ext_ip = await self.ptero.get_external_ip()
      self._ext_ip_cache = (ext_ip, now + 300.0)

    # Query all servers concurrently in parallel without side effects
    dtos = await asyncio.gather(
        *(
            self.get_single_server_status(cfg, ext_ip, idx, srv)
            for idx, srv in enumerate(cfg.servers)
        )
    )

    servers_status = [dto.model_dump() for dto in dtos]

    preview_data = None
    active_preview = self.preview_store.get_preview()
    if active_preview:
      preview_data = {
          "server_name": active_preview.server_name,
          "message": active_preview.message,
          "embed": active_preview.embed,
          "timestamp": active_preview.timestamp,
      }
      # If legacy markdown_formatter was explicitly supplied, preserve formatted fields
      if self.markdown_formatter is not None:
        formatter = self.markdown_formatter
        embed_desc = (
            active_preview.embed.get("description", "")
            if active_preview.embed
            else ""
        )
        preview_data["formatted_message"] = str(formatter(active_preview.message))
        preview_data["formatted_description"] = (
            str(formatter(embed_desc)) if embed_desc else ""
        )

    if self.runtime_state:
      gst = self.runtime_state.get_global_state()
      last_check = gst.last_check
      last_status = gst.last_status
    else:
      last_check = cfg.last_check
      last_status = cfg.last_status

    return {
        "app_version": APP_VERSION,
        "commit_code": COMMIT_CODE,
        "last_check": last_check,
        "last_status": last_status,
        "test_mode": cfg.test_mode,
        "servers": servers_status,
        "preview": preview_data,
    }
