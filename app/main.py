import asyncio
from contextlib import asynccontextmanager
import logging
import os
import time
from app.adapters.a2s import A2SAdapter
from app.adapters.discord import DiscordAdapter
from app.adapters.power_tracker import PowerStateTracker
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.repository import ConfigRepository
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.adapters.vcs import resolve_commit_code
from app.core.config import APP_VERSION, get_commit_code
from app.services.announcement_service import AnnouncementService
from app.services.build_simulator import BuildSimulatorStore
from app.services.countdown import CountdownManager
from app.services.preview_store import WebhookPreviewStore
from app.services.runtime_state import RuntimeStateStore
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.services.telemetry import CallTracker
from app.services.updater import UpdateOrchestrator
from app.core.exceptions import DomainError
from app.web.routes import router as web_router
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import mimetypes

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("updater.main")


@asynccontextmanager
async def lifespan(application: FastAPI):
  call_tracker = CallTracker()

  async def on_request(request: httpx.Request):
    request.extensions["start_time"] = time.time()

  async def on_response(response: httpx.Response):
    start = response.request.extensions.get("start_time", time.time())
    duration_ms = (time.time() - start) * 1000
    endpoint_name = CallTracker.normalize_endpoint(str(response.url))
    call_tracker.record(
        endpoint=endpoint_name,
        method=response.request.method,
        status=str(response.status_code),
        duration_ms=duration_ms,
        details=response.url.path or str(response.url),
    )

  repo = ConfigRepository()
  cfg = repo.load()

  ssl_verify_env = os.getenv("SSL_VERIFY")
  if ssl_verify_env is not None and ssl_verify_env.strip() != "":
    ssl_verify = ssl_verify_env.strip().lower() in ("true", "1", "yes", "on")
  else:
    ssl_verify = bool(getattr(cfg, "ssl_verify", False))

  if not ssl_verify:
    logger.warning(
        "SSL verification is disabled (ssl_verify=False). Set ssl_verify=True in settings for verified TLS certificates."
    )

  async with httpx.AsyncClient(
      timeout=15.0,
      verify=ssl_verify,
      event_hooks={"request": [on_request], "response": [on_response]},
  ) as http_client:
    runtime_state = RuntimeStateStore()
    runtime_state.seed_from_config(cfg)

    power_tracker = PowerStateTracker()
    ptero = PterodactylAdapter(client=http_client, tracker=power_tracker)
    real_steam = SteamAdapter(client=http_client)
    discord = DiscordAdapter(client=http_client)
    a2s = A2SAdapter(call_tracker=call_tracker)

    countdown = CountdownManager()
    preview_store = WebhookPreviewStore()
    simulator_store = BuildSimulatorStore()

    simulated_steam = SimulatedSteamAdapter(
        real_steam=real_steam,
        simulator_store=simulator_store,
        repository=repo,
    )

    announcement_service = AnnouncementService(
        repository=repo,
        ptero=ptero,
        steam=simulated_steam,
        discord=discord,
        preview_store=preview_store,
    )

    orchestrator = UpdateOrchestrator(
        repository=repo,
        ptero=ptero,
        steam=simulated_steam,
        countdown=countdown,
        announcements=announcement_service,
        simulator_store=simulator_store,
        runtime_state=runtime_state,
    )

    server_service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=simulated_steam,
        simulator_store=simulator_store,
        countdown=countdown,
        announcements=announcement_service,
        runtime_state=runtime_state,
        orchestrator=orchestrator,
    )


    commit_code = resolve_commit_code()
    from app.web.templating import templates
    templates.env.globals["commit_code"] = commit_code

    status_service = StatusAggregationService(
        repository=repo,
        ptero=ptero,
        countdown=countdown,
        preview_store=preview_store,
        orchestrator=orchestrator,
        a2s=a2s,
        call_tracker=call_tracker,
        runtime_state=runtime_state,
        power_tracker=power_tracker,
        commit_code=commit_code,
    )

    application.state.commit_code = commit_code
    application.state.repo = repo
    application.state.runtime_state = runtime_state
    application.state.power_tracker = power_tracker
    application.state.ptero = ptero
    application.state.steam = simulated_steam
    application.state.discord = discord
    application.state.a2s = a2s
    application.state.countdown = countdown
    application.state.preview_store = preview_store
    application.state.simulator_store = simulator_store
    application.state.orchestrator = orchestrator
    application.state.server_service = server_service
    application.state.status_service = status_service
    application.state.announcements = announcement_service
    application.state.call_tracker = call_tracker
    application.state.server_config_service = server_service.config_service
    application.state.server_power_service = server_service.power_service
    application.state.inspection_service = orchestrator.inspection_service
    application.state.countdown_coordinator = orchestrator.countdown_coordinator

    orchestrator.start_loop()
    logger.info("Application initialized. Background updater loop started.")

    yield

    orchestrator.stop_loop()
    cancelled_tasks = orchestrator.cancel_all_countdowns(
        reason="Application shutdown"
    )
    if cancelled_tasks:
      await asyncio.gather(*cancelled_tasks, return_exceptions=True)
    if orchestrator.loop_task:
      try:
        await orchestrator.loop_task
      except asyncio.CancelledError:
        pass
    logger.info("Background updater loop gracefully stopped.")


STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Pterodactyl Multi-Server Monitor", version=APP_VERSION, lifespan=lifespan)
app.state.commit_code = get_commit_code()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(web_router)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
  logger.error(
      f"Domain error processing {request.method} {request.url.path}: {exc}"
  )
  status_code = getattr(exc, "status_code", None) or 400
  return JSONResponse(
      status_code=status_code,
      content={
          "status": "error",
          "error": exc.__class__.__name__,
          "message": str(exc),
      },
  )

if __name__ == "__main__":
  import uvicorn

  uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)