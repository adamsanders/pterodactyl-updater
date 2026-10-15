import asyncio
from contextlib import asynccontextmanager
import logging
import time
from app.adapters.a2s import A2SAdapter
from app.adapters.discord import DiscordAdapter
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.repository import ConfigRepository
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.core.config import APP_VERSION
from app.services.build_simulator import BuildSimulatorStore
from app.services.countdown import CountdownManager
from app.services.preview_store import WebhookPreviewStore
from app.services.server_service import ServerService
from app.services.telemetry import CallTracker
from app.services.updater import UpdateOrchestrator
from app.web.routes import router as web_router
from fastapi import FastAPI
import httpx

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

  async with httpx.AsyncClient(
      timeout=15.0,
      verify=False,
      event_hooks={"request": [on_request], "response": [on_response]},
  ) as http_client:
    repo = ConfigRepository()
    ptero = PterodactylAdapter(client=http_client)
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

    orchestrator = UpdateOrchestrator(
        repository=repo,
        ptero=ptero,
        steam=simulated_steam,
        discord=discord,
        preview_store=preview_store,
        countdown=countdown,
        simulator_store=simulator_store,
    )

    server_service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=simulated_steam,
        discord=discord,
        preview_store=preview_store,
        simulator_store=simulator_store,
        countdown=countdown,
    )

    application.state.repo = repo
    application.state.ptero = ptero
    application.state.steam = simulated_steam
    application.state.discord = discord
    application.state.a2s = a2s
    application.state.countdown = countdown
    application.state.preview_store = preview_store
    application.state.simulator_store = simulator_store
    application.state.orchestrator = orchestrator
    application.state.server_service = server_service
    application.state.call_tracker = call_tracker

    bg_task = asyncio.create_task(orchestrator.start_background_loop())
    logger.info("Application initialized. Background updater loop started.")

    yield

    bg_task.cancel()
    try:
      await bg_task
    except asyncio.CancelledError:
      pass
    logger.info("Background updater loop gracefully stopped.")


app = FastAPI(title="Pterodactyl Multi-Server Monitor", version=APP_VERSION, lifespan=lifespan)
app.include_router(web_router)

if __name__ == "__main__":
  import uvicorn

  uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)