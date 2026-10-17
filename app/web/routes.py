import inspect
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
from app.core.models import (
    DetectedServerDetails,
    PowerSignal,
    ServerUpdateStatus,
    SteamSearchResult,
)
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
from app.web.schemas import (
    DashboardViewModel,
    LookupNameResponse,
    PowerActionResponse,
    ServerCardViewModel,
    SettingsFormData,
    SimulateBuildRequest,
    SingleServerSaveRequest,
    SyncNameRequest,
)
from app.web.filters import discord_markdown
from app.web.templating import templates
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()



@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    repo: ConfigRepositoryProtocol = Depends(get_repo),
    countdown: CountdownManagerProtocol = Depends(get_countdown),
    preview_store: Optional[WebhookPreviewStore] = Depends(get_preview_store),
    runtime_state: Optional[RuntimeStateStoreProtocol] = Depends(get_runtime_state),
):
  cfg = repo.load()
  last_check = "Never"
  runtime_states = {}
  if runtime_state:
    gst = runtime_state.get_global_state()
    last_check = gst.last_check
    for srv in cfg.servers:
      if srv.server_id:
        st = runtime_state.get_server_state(srv.server_id)
        runtime_states[srv.server_id] = st
  else:
    last_check = cfg.last_check

  preview = preview_store.get_preview() if preview_store else None

  commit_code = (
      getattr(request.app.state, "commit_code", None)
      if hasattr(request, "app") and hasattr(request.app, "state")
      else None
  ) or COMMIT_CODE

  vm = DashboardViewModel.from_domain(
      config=cfg,
      runtime_states=runtime_states,
      countdown=countdown,
      last_check=last_check,
      app_version=APP_VERSION,
      commit_code=commit_code,
      preview=preview,
  )

  return templates.TemplateResponse(
      request=request,
      name="dashboard.html",
      context={
          "vm": vm,
          "dashboard": vm,
          "cfg": vm,
          "last_check": vm.last_check,
          "runtime_states": runtime_states,
          "countdown": countdown,
          "preview": vm.preview,
          "app_version": vm.app_version,
          "version": vm.app_version,
          "commit_code": vm.commit_code,
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
  if snapshot.get("preview"):
    prev = snapshot["preview"]
    if "formatted_message" not in prev:
      prev["formatted_message"] = str(discord_markdown(prev.get("message", "")))
    if "formatted_description" not in prev:
      embed_desc = (
          prev.get("embed", {}).get("description", "")
          if prev.get("embed")
          else ""
      )
      prev["formatted_description"] = (
          str(discord_markdown(embed_desc)) if embed_desc else ""
      )
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
    payload: SimulateBuildRequest,
    service: ServerService = Depends(get_service),
):
  server_ident = payload.server_id if payload.server_id is not None else payload.server_idx
  build_id = str(payload.build_id).strip()

  await service.trigger_simulated_build(server_ident, build_id)
  return JSONResponse({"status": "ok", "build_id": build_id})


@router.post("/api/test/clear-preview")
async def clear_preview(
    previews: WebhookPreviewStore = Depends(get_preview_store),
):
  previews.clear()
  return JSONResponse({"status": "ok"})


@router.get("/api/servers/lookup-name", response_model=LookupNameResponse)
async def lookup_server_name(
    server_id: str = "",
    service: ServerService = Depends(get_service),
):
  name = await service.lookup_server_name(server_id)
  return JSONResponse({"status": "ok", "name": name})


@router.get("/api/servers/detect-details", response_model=DetectedServerDetails)
async def detect_server_details(
    server_id: str = "",
    service: ServerService = Depends(get_service),
):
  details = await service.detect_server_details(server_id)
  data = details.model_dump() if hasattr(details, "model_dump") else details
  return JSONResponse({"status": "ok", "details": data})


@router.get("/api/steam/search", response_model=list[SteamSearchResult])
async def search_steam_games(
    q: str = "",
    service: ServerService = Depends(get_service),
):
  results = await service.search_steam_games(q)
  serialized = [
      r.model_dump(exclude_none=True) if hasattr(r, "model_dump") else r
      for r in results
  ]
  return JSONResponse({"status": "ok", "results": serialized})


@router.post("/api/servers/{server_id}/sync-name")
async def sync_server_name(
    server_id: str,
    payload: Optional[SyncNameRequest] = None,
    service: ServerService = Depends(get_service),
):
  sid_override = payload.server_id if payload and payload.server_id else None
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
  res = service.update_server_toggle(server_id, field, val)
  if inspect.isawaitable(res):
    await res
  return JSONResponse({"status": "ok", "field": field, "value": val})


@router.post("/api/servers/{server_id}/save")
async def save_single_server_route(
    server_id: str,
    payload: SingleServerSaveRequest,
    service: ServerService = Depends(get_service),
):
  updated = await service.save_single_server(server_id, payload.to_command())
  return JSONResponse({"status": "ok", "server": updated.model_dump()})


@router.post("/api/servers/{server_id}/power/{action}", response_model=PowerActionResponse)
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
  command = await SettingsFormData.to_command(
      await request.form(), repo.load().servers
  )
  res = service.save_settings(command)
  if inspect.isawaitable(res):
    await res
  return RedirectResponse(url="/?toast=saved", status_code=303)


@router.post("/add-server")
async def add_server(
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  command = await SettingsFormData.to_command(
      await request.form(), repo.load().servers
  )
  res = service.add_server(command)
  if inspect.isawaitable(res):
    await res
  return RedirectResponse(url="/?toast=server_added", status_code=303)


@router.post("/delete-server/{server_id}")
async def delete_server(
    server_id: str,
    request: Request,
    service: ServerService = Depends(get_service),
    repo: ConfigRepositoryProtocol = Depends(get_repo),
):
  command = await SettingsFormData.to_command(
      await request.form(), repo.load().servers
  )
  res = service.delete_server(server_id, command)
  if inspect.isawaitable(res):
    await res
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
  command = await SettingsFormData.to_command(raw_form, servers)
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

  await service.rename_server(server_id, new_name, command)
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