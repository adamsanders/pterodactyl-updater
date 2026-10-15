import asyncio
from app.adapters.a2s import A2SAdapter
from app.core.config import APP_VERSION, COMMIT_CODE, resolve_query_port
from app.core.models import ServerModel, ServerStatusDTO
from app.core.protocols import (
    A2SGateway,
    CallTrackerProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    PterodactylGateway,
)
from app.services.preview_store import WebhookPreviewStore
from app.services.server_service import ServerService
from app.services.updater import UpdateOrchestrator
from app.web.filters import discord_markdown
from app.web.schemas import SettingsFormData
from app.web.templating import templates
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()


def get_service(request: Request) -> ServerService:
  return request.app.state.server_service


def get_orchestrator(request: Request) -> UpdateOrchestrator:
  return request.app.state.orchestrator


def get_repo(request: Request) -> ConfigRepositoryProtocol:
  return request.app.state.repo


def get_ptero(request: Request) -> PterodactylGateway:
  return request.app.state.ptero


def get_countdown(request: Request) -> CountdownManagerProtocol:
  return request.app.state.countdown


def get_preview_store(request: Request) -> WebhookPreviewStore:
  return request.app.state.preview_store


def get_a2s(request: Request) -> A2SGateway:
  if not hasattr(request.app.state, "a2s"):
    request.app.state.a2s = A2SAdapter()
  return request.app.state.a2s


def get_call_tracker(request: Request) -> CallTrackerProtocol:
  return request.app.state.call_tracker


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    repo: ConfigRepositoryProtocol = Depends(get_repo),
    countdown: CountdownManagerProtocol = Depends(get_countdown),
):
  return templates.TemplateResponse(
      request=request,
      name="dashboard.html",
      context={
          "cfg": repo.load(),
          "countdown": countdown,
          "app_version": APP_VERSION,
          "commit_code": COMMIT_CODE,
      },
  )


@router.get("/api/telemetry")
async def get_telemetry(
    tracker: CallTrackerProtocol = Depends(get_call_tracker),
):
  return JSONResponse(tracker.get_telemetry_snapshot())


@router.post("/api/telemetry/clear")
async def clear_telemetry(
    tracker: CallTrackerProtocol = Depends(get_call_tracker),
):
  tracker.clear()
  return JSONResponse({"status": "ok"})


@router.get("/api/status")
async def get_status_api(
    repo: ConfigRepositoryProtocol = Depends(get_repo),
    ptero: PterodactylGateway = Depends(get_ptero),
    countdown: CountdownManagerProtocol = Depends(get_countdown),
    previews: WebhookPreviewStore = Depends(get_preview_store),
    orchestrator: UpdateOrchestrator = Depends(get_orchestrator),
    a2s: A2SGateway = Depends(get_a2s),
    tracker: CallTrackerProtocol = Depends(get_call_tracker),
):
  cfg = repo.load()

  tracker.record(
      endpoint="Internal: /api/status Poll",
      method="GET",
      status="200",
      duration_ms=0.5,
      details="Client dashboard live sync",
  )

  ext_ip = await ptero.get_external_ip()

  async def get_single_server_status(
      idx: int, srv: ServerModel
  ) -> tuple[ServerStatusDTO, bool]:
    dirty = False
    power = "unknown"
    if cfg.panel_url and cfg.api_key and srv.server_id:
      power = await ptero.get_power_state(
          cfg.panel_url, cfg.api_key, srv.server_id
      )

    # Real-time countdown cancellation if power state changed externally
    if countdown.is_running(srv.server_id) and power in (
        "starting",
        "stopping",
        "offline",
    ):
      countdown.stop(srv.server_id)
      srv.last_status = f"Manual {power} detected — countdown cancelled"
      dirty = True

    # Immediate build inspection the instant a server finishes booting into Online
    if ptero.consume_startup_transition(srv.server_id):
      asyncio.create_task(
          orchestrator.run_update_check(target_server_id=srv.server_id)
      )

    target_ts = countdown.get_target(srv.server_id)
    rem = countdown.get_remaining(srv.server_id)
    is_upd = countdown.is_running(srv.server_id) or (
        srv.current_build != srv.latest_build
        and srv.current_build not in ("Unknown", "?")
        and srv.latest_build not in ("Unknown", "?")
    )

    internal_ip, game_port = None, None
    if cfg.panel_url and cfg.api_key and srv.server_id:
      internal_ip, game_port = await ptero.get_server_allocation(
          cfg.panel_url, cfg.api_key, srv.server_id
      )

    query_port = (
        resolve_query_port(srv.app_id, game_port) if game_port else None
    )

    player_count, max_players = None, None
    if power == "running" and ext_ip and query_port:
      player_count, max_players = await a2s.get_player_count(
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

  # Query all servers concurrently in parallel
  results = await asyncio.gather(
      *(
          get_single_server_status(idx, srv)
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
    repo.save(cfg)

  preview_data = None
  active_preview = previews.get_preview()
  if active_preview:
    preview_data = {
        "server_name": active_preview.server_name,
        "message": active_preview.message,
        "formatted_message": str(discord_markdown(active_preview.message)),
        "embed": active_preview.embed,
        "formatted_description": (
            str(
                discord_markdown(active_preview.embed.get("description", ""))
            )
            if active_preview.embed
            else ""
        ),
        "timestamp": active_preview.timestamp,
    }

  return JSONResponse({
      "app_version": APP_VERSION,
      "commit_code": COMMIT_CODE,
      "last_check": cfg.last_check,
      "last_status": cfg.last_status,
      "test_mode": cfg.test_mode,
      "servers": servers_status,
      "preview": preview_data,
  })


@router.post("/toggle-test-mode")
async def toggle_test_mode(
    request: Request,
    service: ServerService = Depends(get_service),
    orchestrator: UpdateOrchestrator = Depends(get_orchestrator),
):
  try:
    enabled = bool((await request.json()).get("enabled", False))
  except Exception:
    enabled = False

  result = service.toggle_test_mode(enabled)
  orchestrator.clear_restarted_build()
  if not enabled:
    await orchestrator.run_update_check()

  return {"status": "ok", "test_mode": result}


@router.post("/api/test/simulate-build")
async def simulate_build(
    request: Request,
    service: ServerService = Depends(get_service),
    orchestrator: UpdateOrchestrator = Depends(get_orchestrator),
):
  data = await request.json()
  server_idx = int(data.get("server_idx", 0))
  build_id = str(data.get("build_id", "")).strip()

  success, err, target_server_id = service.simulate_build_update(
      server_idx, build_id
  )
  if not success:
    return JSONResponse(
        {"status": "error", "message": err or "Simulation failed"},
        status_code=400,
    )

  orchestrator.clear_restarted_build(target_server_id)
  await orchestrator.run_update_check(target_server_id=target_server_id)
  return JSONResponse({"status": "ok", "build_id": build_id})


@router.post("/api/test/clear-preview")
async def clear_preview(
    previews: WebhookPreviewStore = Depends(get_preview_store),
):
  previews.clear()
  return JSONResponse({"status": "ok"})


@router.post("/api/servers/{server_idx}/power/{action}")
async def server_power_action(
    server_idx: int,
    action: str,
    service: ServerService = Depends(get_service),
    orchestrator: UpdateOrchestrator = Depends(get_orchestrator),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  cfg = repo.load()
  if 0 <= server_idx < len(cfg.servers):
    orchestrator.clear_restarted_build(cfg.servers[server_idx].server_id)
  success, err = await service.send_power_action(server_idx, action)
  if not success:
    return JSONResponse(
        {"status": "error", "message": err or "Action failed"}, status_code=400
    )
  return JSONResponse(
      {"status": "ok", "action": action, "server_idx": server_idx}
  )


@router.post("/save")
async def save_settings(
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  settings = await SettingsFormData.from_form(
      await request.form(), repo.load().servers
  )
  service.save_settings(settings)
  return RedirectResponse(url="/?toast=saved", status_code=303)


@router.post("/add-server")
async def add_server(
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  settings = await SettingsFormData.from_form(
      await request.form(), repo.load().servers
  )
  service.add_server(settings)
  return RedirectResponse(url="/?toast=server_added", status_code=303)


@router.post("/delete-server/{server_idx}")
async def delete_server(
    server_idx: int,
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  settings = await SettingsFormData.from_form(
      await request.form(), repo.load().servers
  )
  service.delete_server(server_idx, settings)
  return RedirectResponse(url="/?toast=server_removed", status_code=303)


@router.post("/rename-server/{server_idx}")
async def rename_server(
    server_idx: int,
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  raw_form = await request.form()
  settings = await SettingsFormData.from_form(raw_form, repo.load().servers)
  new_name = raw_form.get(f"srv_name_{server_idx}", "").strip()
  await service.rename_server(server_idx, new_name, settings)
  return RedirectResponse(url="/?toast=renamed", status_code=303)


@router.post("/test-webhook/{server_idx}")
async def test_webhook(
    server_idx: int, service: ServerService = Depends(get_service)
):
  await service.test_webhook(server_idx)
  return RedirectResponse(url="/", status_code=303)


@router.post("/check-now")
async def check_now(
    request: Request,
    orchestrator: UpdateOrchestrator = Depends(get_orchestrator),
    ptero: PterodactylGateway = Depends(get_ptero),
):
  # Invalidate cached states across all servers before running a unified update check
  ptero.invalidate_power_cache()
  await orchestrator.run_update_check()
  if request.headers.get("accept") == "application/json":
    return JSONResponse({"status": "ok"})
  return RedirectResponse(url="/?toast=checked", status_code=303)