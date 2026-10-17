import asyncio
from contextlib import asynccontextmanager
import inspect
import logging
import os
import time
from typing import Any, AsyncIterator, Optional

import httpx

from app.adapters.a2s import A2SAdapter
from app.adapters.discord import DiscordAdapter
from app.adapters.power_tracker import PowerStateTracker
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.repository import ConfigRepository
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.core.models import AppConfigModel
from app.core.protocols import (
    BuildSimulatorProtocol,
    CallTrackerProtocol,
    ConfigRepositoryGateway,
    CountdownGateway,
    NotificationGateway,
    PlayerQueryGateway,
    PowerTrackerGateway,
    PterodactylGateway,
    RuntimeStateStoreProtocol,
    SteamGateway,
    WebhookPreviewStoreProtocol,
)
from app.services.build_simulator import BuildSimulatorStore
from app.services.countdown import CountdownManager
from app.services.preview_store import WebhookPreviewStore
from app.services.runtime_state import RuntimeStateStore
from app.services.telemetry import CallTracker

logger = logging.getLogger("updater.infrastructure")


def resolve_ssl_verify(cfg: Optional[AppConfigModel] = None) -> bool:
  """Resolves whether TLS certificate verification is active based on environment or config."""
  ssl_verify_env = os.getenv("SSL_VERIFY")
  if ssl_verify_env is not None and ssl_verify_env.strip() != "":
    return ssl_verify_env.strip().lower() in ("true", "1", "yes", "on")
  if cfg is not None:
    return bool(getattr(cfg, "ssl_verify", False))
  return False


def create_http_event_hooks(
    call_tracker: Optional[CallTrackerProtocol] = None,
) -> dict:
  """Builds event hooks for httpx.AsyncClient to record endpoint telemetry via CallTracker."""
  if call_tracker is None:
    return {}

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

  return {"request": [on_request], "response": [on_response]}


def create_http_client(
    verify: bool = False,
    call_tracker: Optional[CallTrackerProtocol] = None,
    timeout: float = 15.0,
) -> httpx.AsyncClient:
  """Factory producing an isolated httpx.AsyncClient with configured verification and event hooks."""
  hooks = create_http_event_hooks(call_tracker)
  return httpx.AsyncClient(
      timeout=timeout,
      verify=verify,
      event_hooks=hooks,
  )


@asynccontextmanager
async def async_client_session(
    verify: bool = False,
    call_tracker: Optional[CallTrackerProtocol] = None,
    timeout: float = 15.0,
    client: Optional[httpx.AsyncClient] = None,
) -> AsyncIterator[httpx.AsyncClient]:
  """Async context manager isolating the lifecycle of an external HTTP client."""
  if client is None:
    client = create_http_client(
        verify=verify, call_tracker=call_tracker, timeout=timeout
    )
  try:
    if hasattr(client, "__aenter__") and callable(client.__aenter__):
      async with client as session:
        yield session
    else:
      yield client
  finally:
    await close_resources(http_client=client)


def create_config_repository(
    filepath: Optional[str] = None,
) -> ConfigRepositoryGateway:
  return ConfigRepository(filepath=filepath) if filepath else ConfigRepository()


def create_power_tracker() -> PowerTrackerGateway:
  return PowerStateTracker()


def create_pterodactyl_gateway(
    client: httpx.AsyncClient,
    tracker: Optional[PowerTrackerGateway] = None,
) -> PterodactylGateway:
  return PterodactylAdapter(client=client, tracker=tracker)


def create_steam_gateway(client: httpx.AsyncClient) -> SteamGateway:
  return SteamAdapter(client=client)


def create_simulated_steam_gateway(
    real_steam: SteamGateway,
    simulator_store: BuildSimulatorProtocol,
    repository: ConfigRepositoryGateway,
) -> SteamGateway:
  return SimulatedSteamAdapter(
      real_steam=real_steam,
      simulator_store=simulator_store,
      repository=repository,
  )


def create_discord_gateway(client: httpx.AsyncClient) -> NotificationGateway:
  return DiscordAdapter(client=client)


def create_a2s_gateway(
    call_tracker: Optional[CallTrackerProtocol] = None,
) -> PlayerQueryGateway:
  return A2SAdapter(call_tracker=call_tracker)


def create_runtime_state_store(
    config: Optional[AppConfigModel] = None,
) -> RuntimeStateStoreProtocol:
  store = RuntimeStateStore()
  if config:
    store.seed_from_config(config)
  return store


def create_countdown_manager() -> CountdownGateway:
  return CountdownManager()


def create_preview_store() -> WebhookPreviewStoreProtocol:
  return WebhookPreviewStore()


def create_simulator_store() -> BuildSimulatorProtocol:
  return BuildSimulatorStore()


def create_call_tracker() -> CallTrackerProtocol:
  return CallTracker()


async def close_resources(
    http_client: Optional[httpx.AsyncClient] = None,
    *other_resources: Any,
) -> None:
  """Closes and releases external network and HTTP client resources cleanly."""
  resources = ([http_client] if http_client is not None else []) + list(
      other_resources
  )
  for res in resources:
    if res is None:
      continue
    try:
      if hasattr(res, "aclose") and callable(res.aclose):
        if not getattr(res, "is_closed", False):
          res_aclose = res.aclose()
          if inspect.isawaitable(res_aclose):
            await res_aclose
      elif hasattr(res, "close") and callable(res.close):
        if not getattr(res, "is_closed", False):
          res_close = res.close()
          if inspect.isawaitable(res_close):
            await res_close
    except Exception as e:
      logger.error("Error closing resource %r: %s", res, e)


__all__ = [
    "resolve_ssl_verify",
    "create_http_event_hooks",
    "create_http_client",
    "async_client_session",
    "create_config_repository",
    "create_power_tracker",
    "create_pterodactyl_gateway",
    "create_steam_gateway",
    "create_simulated_steam_gateway",
    "create_discord_gateway",
    "create_a2s_gateway",
    "create_runtime_state_store",
    "create_countdown_manager",
    "create_preview_store",
    "create_simulator_store",
    "create_call_tracker",
    "close_resources",
]
