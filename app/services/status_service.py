import asyncio
import logging
from typing import Any, Callable, Optional

from app.core.config import APP_VERSION, COMMIT_CODE, resolve_query_port
from app.core.models import AppConfigModel, ServerModel, ServerStatusDTO
from app.core.protocols import (
    A2SGateway,
    CallTrackerProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
)
from app.services.preview_store import WebhookPreviewStore
from app.services.updater import UpdateOrchestrator

logger = logging.getLogger("updater.status_service")


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

  async def get_single_server_status(
      self,
      cfg: AppConfigModel,
      ext_ip: Optional[str],
      idx: int,
      srv: ServerModel,
  ) -> ServerStatusDTO:
    """Pure query: reads telemetry, allocation, and power state for an individual game server."""
    power = "unknown"
    if cfg.panel_url and cfg.api_key and srv.server_id:
      power = await self.ptero.get_power_state(
          cfg.panel_url, cfg.api_key, srv.server_id
      )

    target_ts = self.countdown.get_target(srv.server_id)
    rem = self.countdown.get_remaining(srv.server_id)

    cur_build = srv.current_build
    lat_build = srv.latest_build
    srv_status = srv.last_status

    if self.runtime_state and srv.server_id:
      st = self.runtime_state.get_server_state(srv.server_id)
      if st.current_build != "Unknown":
        cur_build = st.current_build
      if st.latest_build != "Unknown":
        lat_build = st.latest_build
      if st.last_status != "Idle":
        srv_status = st.last_status

    is_upd = (power != "offline") and (
        self.countdown.is_running(srv.server_id)
        or (
            cur_build != lat_build
            and cur_build not in ("Unknown", "?")
            and lat_build not in ("Unknown", "?")
        )
    )

    internal_ip, game_port = None, None
    if cfg.panel_url and cfg.api_key and srv.server_id:
      internal_ip, game_port = await self.ptero.get_server_allocation(
          cfg.panel_url, cfg.api_key, srv.server_id
      )

    query_port = (
        resolve_query_port(srv.app_id, game_port) if game_port else None
    )

    player_count, max_players = None, None
    if self.a2s and power == "running" and ext_ip and query_port:
      player_count, max_players = await self.a2s.get_player_count(
          ext_ip, query_port
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
    """Collates full fleet telemetry as a pure, side-effect free read query."""
    cfg = self.repository.load()

    if self.call_tracker:
      self.call_tracker.record(
          endpoint="Internal: /api/status Poll",
          method="GET",
          status="200",
          duration_ms=0.5,
          details="Client dashboard live sync",
      )

    ext_ip = await self.ptero.get_external_ip()

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
      formatter = self.markdown_formatter or (lambda s: s)
      embed_desc = (
          active_preview.embed.get("description", "")
          if active_preview.embed
          else ""
      )
      preview_data = {
          "server_name": active_preview.server_name,
          "message": active_preview.message,
          "formatted_message": str(formatter(active_preview.message)),
          "embed": active_preview.embed,
          "formatted_description": (
              str(formatter(embed_desc)) if embed_desc else ""
          ),
          "timestamp": active_preview.timestamp,
      }

    last_check = cfg.last_check
    last_status = cfg.last_status
    if self.runtime_state:
      gst = self.runtime_state.get_global_state()
      if gst.last_check != "Never":
        last_check = gst.last_check
      if gst.last_status != "Idle":
        last_status = gst.last_status

    return {
        "app_version": APP_VERSION,
        "commit_code": COMMIT_CODE,
        "last_check": last_check,
        "last_status": last_status,
        "test_mode": cfg.test_mode,
        "servers": servers_status,
        "preview": preview_data,
    }
