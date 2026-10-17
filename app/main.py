from contextlib import asynccontextmanager
import logging
import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.composition import (
    bind_container_to_app,
    build_container,
    shutdown_container,
)
from app.core.config import APP_VERSION, get_commit_code
from app.core.exceptions import DomainError
import app.infrastructure as infrastructure
from app.infrastructure import (
    async_client_session,
    create_call_tracker,
    create_config_repository,
    resolve_ssl_verify,
)
from app.services.updater import UpdateOrchestrator
from app.web.routes import router as web_router

# Compatibility aliases for external test harnesses
ConfigRepository = create_config_repository
httpx = infrastructure.httpx

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("updater.main")


@asynccontextmanager
async def lifespan(application: FastAPI):
  call_tracker = create_call_tracker()

  repo = ConfigRepository()
  cfg = repo.load()

  ssl_verify = resolve_ssl_verify(cfg)
  if not ssl_verify:
    logger.warning(
        "SSL verification is disabled (ssl_verify=False). Set ssl_verify=True in settings for verified TLS certificates."
    )

  async with async_client_session(
      verify=ssl_verify,
      call_tracker=call_tracker,
      timeout=15.0,
  ) as http_client:
    container = build_container(
        cfg=cfg,
        repo=repo,
        http_client=http_client,
        call_tracker=call_tracker,
    )
    bind_container_to_app(application, container)

    container.orchestrator.start_loop()
    logger.info("Application initialized. Background updater loop started.")

    try:
      yield
    finally:
      await shutdown_container(container)
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