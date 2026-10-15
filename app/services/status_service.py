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
      orchestrator: UpdateOrchestrator,
      a2s: A2SGateway,
      call_tracker: Optional[CallTrackerProtocol] = None,
      markdown_formatter: Optional[Callable[[str], Any]] = None,
  ):
    self.repository = repository
    self.ptero = ptero
    self.countdown = countdown
    self.preview_store = preview_store
    self.orchestrator = orchestrator
    self.a2s = a2s
    self.call_tracker = call_tracker
    self.markdown_formatter = markdown_formatter

  async def get_single_server_status(
      self,
      cfg: AppConfigModel,
      ext_ip: Optional[str],
      idx: int,
      srv: ServerModel,
  ) -> tuple[ServerStatusDTO, bool]:
    """Queries telemetry, allocation, and power state for an individual game server."""
    dirty = False
    power = "unknown"
    if cfg.panel_url and cfg.api_key and srv.server_id:
      power = await self.ptero.get_power_state(
          cfg.panel_url, cfg.api_key, srv.server_id
      )

    # Real-time countdown cancellation if power state changed externally
    if self.countdown.is_running(srv.server_id) and power in (
        "starting",
        "stopping",
        "offline",
    ):
      self.countdown.stop(srv.server_id)
      srv.last_status = f"Manual {power} detected — countdown cancelled"
      dirty = True

    # Immediate build inspection the instant a server finishes booting into Online
    if self.ptero.consume_startup_transition(srv.server_id):
      asyncio.create_task(
          self.orchestrator.run_update_check(target_server_id=srv.server_id)
      )

    target_ts = self.countdown.get_target(srv.server_id)
    rem = self.countdown.get_remaining(srv.server_id)
    is_upd = (power != "offline") and (
        self.countdown.is_running(srv.server_id)
        or (
            srv.current_build != srv.latest_build
            and srv.current_build not in ("Unknown", "?")
            and srv.latest_build not in ("Unknown", "?")
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
    if power == "running" and ext_ip and query_port:
      player_count, max_players = await self.a2s.get_player_count(
          ext_ip, query_port
      )

    dto = ServerStatusDTO(
        idx=idx,
        server_id=srv.server_id,
        name=srv.name,
        power_state=power,
        current_build=srv.current_build,
        latest_build=srv.latest_build,
        last_status=srv.last_status,
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
    return dto, dirty

  async def get_status_snapshot(self) -> dict[str, Any]:
    """Collates full fleet telemetry, executes concurrent server queries, and builds API payload."""
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

    # Query all servers concurrently in parallel
    results = await asyncio.gather(
        *(
            self.get_single_server_status(cfg, ext_ip, idx, srv)
            for idx, srv in enumerate(cfg.servers)
        )
    )

    servers_status = []
    config_dirty = False
    for dto, is_dirty in results:
      servers_status.append(dto.model_dump())
      if is_dirty:
        config_dirty = True

    if config_dirty:
      self.repository.save(cfg)

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

    return {
        "app_version": APP_VERSION,
        "commit_code": COMMIT_CODE,
        "last_check": cfg.last_check,
        "last_status": cfg.last_status,
        "test_mode": cfg.test_mode,
        "servers": servers_status,
        "preview": preview_data,
    }
