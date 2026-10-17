import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

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
from app.infrastructure import (
    async_client_session,
    close_resources,
    create_a2s_gateway,
    create_call_tracker,
    create_config_repository,
    create_countdown_manager,
    create_discord_gateway,
    create_http_client,
    create_http_event_hooks,
    create_power_tracker,
    create_preview_store,
    create_pterodactyl_gateway,
    create_runtime_state_store,
    create_simulated_steam_gateway,
    create_simulator_store,
    create_steam_gateway,
    resolve_ssl_verify,
)


class TestInfrastructureFactories(unittest.IsolatedAsyncioTestCase):
  """Unit tests for infrastructure layer adapter factories and network client lifecycle."""

  def test_resolve_ssl_verify_from_env_truthy(self):
    for val in ("true", "1", "yes", "on", "TRUE", " true "):
      with patch.dict(os.environ, {"SSL_VERIFY": val}):
        self.assertTrue(resolve_ssl_verify(None), f"Failed for {val}")

  def test_resolve_ssl_verify_from_env_falsy(self):
    for val in ("false", "0", "no", "off", "FALSE", " random "):
      with patch.dict(os.environ, {"SSL_VERIFY": val}):
        self.assertFalse(resolve_ssl_verify(None), f"Failed for {val}")

  def test_resolve_ssl_verify_env_empty_falls_back_to_config(self):
    cfg_true = AppConfigModel(ssl_verify=True)
    cfg_false = AppConfigModel(ssl_verify=False)

    with patch.dict(os.environ, {"SSL_VERIFY": ""}):
      self.assertTrue(resolve_ssl_verify(cfg_true))
      self.assertFalse(resolve_ssl_verify(cfg_false))

    with patch.dict(os.environ, {}, clear=True):
      if "SSL_VERIFY" in os.environ:
        del os.environ["SSL_VERIFY"]
      self.assertTrue(resolve_ssl_verify(cfg_true))
      self.assertFalse(resolve_ssl_verify(cfg_false))
      self.assertFalse(resolve_ssl_verify(None))

  def test_create_http_event_hooks_none_tracker(self):
    hooks = create_http_event_hooks(call_tracker=None)
    self.assertEqual(hooks, {})

  async def test_create_http_event_hooks_records_telemetry(self):
    mock_tracker = MagicMock(spec=CallTrackerProtocol)
    hooks = create_http_event_hooks(call_tracker=mock_tracker)
    self.assertIn("request", hooks)
    self.assertIn("response", hooks)

    on_request = hooks["request"][0]
    on_response = hooks["response"][0]

    req = httpx.Request("GET", "https://panel.example.com/api/client/servers/123")
    await on_request(req)
    self.assertIn("start_time", req.extensions)

    resp = httpx.Response(200, request=req)
    await on_response(resp)
    mock_tracker.record.assert_called_once()
    kwargs = mock_tracker.record.call_args[1]
    self.assertEqual(kwargs.get("method"), "GET")
    self.assertEqual(kwargs.get("status"), "200")

  def test_create_http_client_factory(self):
    client = create_http_client(verify=False, timeout=10.0)
    self.assertIsInstance(client, httpx.AsyncClient)
    self.assertEqual(client.timeout.read, 10.0)

  async def test_async_client_session_context_manager(self):
    async with async_client_session(verify=True, timeout=5.0) as client:
      self.assertIsInstance(client, httpx.AsyncClient)
      self.assertFalse(client.is_closed)
    self.assertTrue(client.is_closed)

  async def test_close_resources_handles_open_and_closed_client(self):
    client = httpx.AsyncClient()
    self.assertFalse(client.is_closed)
    await close_resources(client)
    self.assertTrue(client.is_closed)
    # Re-running on already-closed client must not raise
    await close_resources(client)
    await close_resources(None)

  async def test_async_client_session_with_provided_client(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.__aenter__.return_value = mock_client
    async with async_client_session(client=mock_client) as session:
      self.assertIs(session, mock_client)
    mock_client.aclose.assert_called_once()

  async def test_close_resources_multiple_resources_with_exceptions_handled(self):
    res_failing = AsyncMock()
    res_failing.aclose.side_effect = RuntimeError("Socket failed to close")
    res_failing.is_closed = False

    res_successful = AsyncMock()
    res_successful.is_closed = False

    sync_res = MagicMock(spec=["close", "is_closed"])
    sync_res.is_closed = False

    # Must not raise an exception even if one resource fails
    await close_resources(res_failing, res_successful, sync_res, None)
    res_failing.aclose.assert_called_once()
    res_successful.aclose.assert_called_once()
    sync_res.close.assert_called_once()

  def test_create_gateway_factories_satisfy_protocols(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    repo = create_config_repository()
    self.assertIsInstance(repo, ConfigRepositoryGateway)

    power_tracker = create_power_tracker()
    self.assertIsInstance(power_tracker, PowerTrackerGateway)

    ptero = create_pterodactyl_gateway(mock_client, tracker=power_tracker)
    self.assertIsInstance(ptero, PterodactylGateway)

    steam = create_steam_gateway(mock_client)
    self.assertIsInstance(steam, SteamGateway)

    discord = create_discord_gateway(mock_client)
    self.assertIsInstance(discord, NotificationGateway)

    a2s = create_a2s_gateway()
    self.assertIsInstance(a2s, PlayerQueryGateway)

    sim_store = create_simulator_store()
    self.assertIsInstance(sim_store, BuildSimulatorProtocol)

    sim_steam = create_simulated_steam_gateway(
        real_steam=steam,
        simulator_store=sim_store,
        repository=repo,
    )
    self.assertIsInstance(sim_steam, SteamGateway)

    runtime_state = create_runtime_state_store()
    self.assertIsInstance(runtime_state, RuntimeStateStoreProtocol)

    countdown = create_countdown_manager()
    self.assertIsInstance(countdown, CountdownGateway)

    preview_store = create_preview_store()
    self.assertIsInstance(preview_store, WebhookPreviewStoreProtocol)

    tracker = create_call_tracker()
    self.assertIsInstance(tracker, CallTrackerProtocol)


if __name__ == "__main__":
  unittest.main()
