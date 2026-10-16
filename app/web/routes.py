from typing import Optional
from app.core.config import APP_VERSION, COMMIT_CODE
from app.core.exceptions import (
    ConfigurationError,
    DomainError,
    InvalidPowerActionError,
    PterodactylApiError,
    ServerNotFoundError,
    SimulationError,
)
from app.core.models import PowerSignal
from app.core.protocols import (
    CallTrackerProtocol,
    ConfigRepositoryProtocol,
    CountdownManagerProtocol,
    RuntimeStateStoreProtocol,
)
from app.services.preview_store import WebhookPreviewStore
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.web.dependencies import (
    get_a2s,
    get_call_tracker,
    get_countdown,
    get_orchestrator,
    get_preview_store,
    get_ptero,
    get_repo,
    get_runtime_state,
    get_service,
    get_status_service,
)
from app.web.schemas import SettingsFormData
from app.web.templating import templates
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()



@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    repo: ConfigRepositoryProtocol = Depends(get_repo),
    countdown: CountdownManagerProtocol = Depends(get_countdown),
    runtime_state: Optional[RuntimeStateStoreProtocol] = Depends(get_runtime_state),
):
  cfg = repo.load()
  if runtime_state:
    gst = runtime_state.get_global_state()
    if gst.last_check != "Never":
      cfg.last_check = gst.last_check
    if gst.last_status != "Idle":
      cfg.last_status = gst.last_status
    for srv in cfg.servers:
      st = runtime_state.get_server_state(srv.server_id)
      if st.current_build != "Unknown":
        srv.current_build = st.current_build
      if st.latest_build != "Unknown":
        srv.latest_build = st.latest_build
      if st.last_status != "Idle":
        srv.last_status = st.last_status

  return templates.TemplateResponse(
      request=request,
      name="dashboard.html",
      context={
          "cfg": cfg,
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
    status_service: StatusAggregationService = Depends(get_status_service),
):
  snapshot = await status_service.get_status_snapshot()
  return JSONResponse(snapshot)



@router.post("/toggle-test-mode")
async def toggle_test_mode(
    request: Request,
    service: ServerService = Depends(get_service),
):
  try:
    enabled = bool((await request.json()).get("enabled", False))
  except Exception:
    enabled = False

  result = await service.toggle_test_mode(enabled)
  return {"status": "ok", "test_mode": result}


@router.post("/api/test/simulate-build")
async def simulate_build(
    request: Request,
    service: ServerService = Depends(get_service),
):
  data = await request.json()
  server_ident = data.get("server_id")
  if server_ident is None:
    server_ident = data.get("server_idx", 0)
  build_id = str(data.get("build_id", "")).strip()

  await service.trigger_simulated_build(server_ident, build_id)
  return JSONResponse({"status": "ok", "build_id": build_id})


@router.post("/api/test/clear-preview")
async def clear_preview(
    previews: WebhookPreviewStore = Depends(get_preview_store),
):
  previews.clear()
  return JSONResponse({"status": "ok"})


@router.get("/api/servers/lookup-name")
async def lookup_server_name(
    server_id: str = "",
    service: ServerService = Depends(get_service),
):
  name = await service.lookup_server_name(server_id)
  return JSONResponse({"status": "ok", "name": name})


@router.get("/api/servers/detect-details")
async def detect_server_details(
    server_id: str = "",
    service: ServerService = Depends(get_service),
):
  details = await service.detect_server_details(server_id)
  return JSONResponse({"status": "ok", "details": details})


@router.get("/api/steam/search")
async def search_steam_games(
    q: str = "",
    service: ServerService = Depends(get_service),
):
  results = await service.search_steam_games(q)
  return JSONResponse({"status": "ok", "results": results})


@router.post("/api/servers/{server_id}/sync-name")
async def sync_server_name(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
):
  sid_override = None
  try:
    body = await request.json()
    if isinstance(body, dict):
      sid_override = body.get("server_id")
  except Exception:
    pass

  name = await service.sync_server_name(
      server_id, server_id_override=sid_override
  )
  return JSONResponse({"status": "ok", "name": name})


@router.post("/api/servers/{server_id}/toggle")
async def toggle_server_setting(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
):
  body = await request.json()
  field = body.get("field", "")
  val = bool(body.get("value", False))
  service.update_server_toggle(server_id, field, val)
  return JSONResponse({"status": "ok", "field": field, "value": val})


@router.post("/api/servers/{server_id}/save")
async def save_single_server_route(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
):
  body = await request.json()
  updated = await service.save_single_server(server_id, body)
  return JSONResponse({"status": "ok", "server": updated.model_dump()})


@router.post("/api/servers/{server_id}/power/{action}")
async def server_power_action(
    server_id: str,
    action: str,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  cfg = repo.load()
  idx = service.find_server_index(cfg.servers, server_id)
  target_id = cfg.servers[idx].server_id if idx is not None else server_id

  try:
    signal = PowerSignal.from_str(action)
  except ValueError:
    signal = action

  result = await service.send_power_action(server_id, signal)
  if hasattr(result, "raise_if_failed"):
    result.raise_if_failed(server_id=target_id)
  elif isinstance(result, tuple) and not result[0]:
    err = result[1] if len(result) > 1 else None
    raise PterodactylApiError(err or "Power action failed", status_code=400, server_id=target_id)

  return JSONResponse(
      {
          "status": "ok",
          "action": str(signal),
          "server_id": target_id,
          "server_idx": idx if idx is not None else 0,
      }
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


@router.post("/delete-server/{server_id}")
async def delete_server(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  settings = await SettingsFormData.from_form(
      await request.form(), repo.load().servers
  )
  service.delete_server(server_id, settings)
  return RedirectResponse(url="/?toast=server_removed", status_code=303)


@router.post("/rename-server/{server_id}")
async def rename_server(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  raw_form = await request.form()
  servers = repo.load().servers
  settings = await SettingsFormData.from_form(raw_form, servers)
  idx = service.find_server_index(servers, server_id)
  if idx is None:
    raise ServerNotFoundError(server_id)

  new_name = (
      raw_form.get(f"srv_name_{server_id}")
      or (raw_form.get(f"srv_name_{idx}") if idx is not None else None)
      or ""
  ).strip()
  if not new_name:
    raise ConfigurationError("Server name cannot be empty.")

  await service.rename_server(server_id, new_name, settings)
  return RedirectResponse(url="/?toast=renamed", status_code=303)


@router.post("/test-webhook/{server_id}")
async def test_webhook(
    server_id: str,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  servers = repo.load().servers
  if service.find_server_index(servers, server_id) is None:
    raise ServerNotFoundError(server_id)

  await service.test_webhook(server_id)
  return RedirectResponse(url="/", status_code=303)


@router.post("/check-now")
async def check_now(
    request: Request,
    service: ServerService = Depends(get_service),
):
  await service.trigger_immediate_check()
  if request.headers.get("accept") == "application/json":
    return JSONResponse({"status": "ok"})
  return RedirectResponse(url="/?toast=checked", status_code=303)