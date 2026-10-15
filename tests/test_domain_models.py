import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
import httpx

from app.core.exceptions import (
    A2SQueryError,
    ConfigurationError,
    DomainError,
    InvalidPowerActionError,
    PterodactylApiError,
    ServerNotFoundError,
    SimulationError,
    SteamApiError,
)
from app.core.models import (
    LocalBuildResult,
    OperationResult,
    PlayerMetrics,
    ServerAllocation,
    ServerNameResult,
)
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.steam import SteamAdapter
from app.adapters.a2s import A2SAdapter
from app.main import app


class TestDomainModels(unittest.TestCase):

  def test_server_allocation_attributes_and_unpacking(self):
    alloc = ServerAllocation(ip="192.168.1.100", port=2456)
    self.assertEqual(alloc.ip, "192.168.1.100")
    self.assertEqual(alloc.port, 2456)

    # Verify tuple unpacking compatibility
    ip, port = alloc
    self.assertEqual(ip, "192.168.1.100")
    self.assertEqual(port, 2456)

    # Defaults
    default_alloc = ServerAllocation()
    self.assertIsNone(default_alloc.ip)
    self.assertIsNone(default_alloc.port)

  def test_player_metrics_attributes_and_unpacking(self):
    metrics = PlayerMetrics(current=5, max=64)
    self.assertEqual(metrics.current, 5)
    self.assertEqual(metrics.max, 64)

    # Verify tuple unpacking compatibility
    curr, max_p = metrics
    self.assertEqual(curr, 5)
    self.assertEqual(max_p, 64)

    # Defaults
    default_metrics = PlayerMetrics()
    self.assertIsNone(default_metrics.current)
    self.assertIsNone(default_metrics.max)

  def test_local_build_result_attributes_and_unpacking(self):
    res = LocalBuildResult(build_id="12345678", error=None)
    self.assertEqual(res.build_id, "12345678")
    self.assertIsNone(res.error)

    # Tuple unpacking
    b_id, err = res
    self.assertEqual(b_id, "12345678")
    self.assertIsNone(err)

    # raise_if_failed success
    self.assertEqual(res.raise_if_failed(), "12345678")

    # Error case
    err_res = LocalBuildResult(build_id=None, error="File not found")
    self.assertIsNone(err_res.build_id)
    self.assertEqual(err_res.error, "File not found")
    with self.assertRaises(DomainError) as ctx:
      err_res.raise_if_failed()
    self.assertIn("File not found", str(ctx.exception))

  def test_server_name_result_attributes_and_unpacking(self):
    res = ServerNameResult(name="My Server", error=None)
    self.assertEqual(res.name, "My Server")
    self.assertIsNone(res.error)

    # Tuple unpacking
    name, err = res
    self.assertEqual(name, "My Server")
    self.assertIsNone(err)

    # raise_if_failed success
    self.assertEqual(res.raise_if_failed(), "My Server")

    # Error case
    err_res = ServerNameResult(name=None, error="Panel HTTP 404")
    self.assertIsNone(err_res.name)
    self.assertEqual(err_res.error, "Panel HTTP 404")
    with self.assertRaises(PterodactylApiError) as ctx:
      err_res.raise_if_failed(PterodactylApiError)
    self.assertIn("Panel HTTP 404", str(ctx.exception))

  def test_operation_result_attributes_and_unpacking(self):
    res = OperationResult(success=True, error=None)
    self.assertTrue(res.success)
    self.assertIsNone(res.error)
    self.assertTrue(bool(res))

    # Tuple unpacking
    success, err = res
    self.assertTrue(success)
    self.assertIsNone(err)

    # raise_if_failed on success
    self.assertIs(res.raise_if_failed(), res)

    # Failure case
    fail_res = OperationResult(success=False, error="Panel HTTP 500")
    self.assertFalse(fail_res.success)
    self.assertEqual(fail_res.error, "Panel HTTP 500")
    self.assertFalse(bool(fail_res))

    with self.assertRaises(DomainError) as ctx:
      fail_res.raise_if_failed()
    self.assertIn("Panel HTTP 500", str(ctx.exception))

    with self.assertRaises(PterodactylApiError) as ctx_custom:
      fail_res.raise_if_failed(PterodactylApiError)
    self.assertIn("Panel HTTP 500", str(ctx_custom.exception))


class TestDomainExceptions(unittest.TestCase):

  def test_domain_error_hierarchy(self):
    self.assertTrue(issubclass(PterodactylApiError, DomainError))
    self.assertTrue(issubclass(SteamApiError, DomainError))
    self.assertTrue(issubclass(A2SQueryError, DomainError))
    self.assertTrue(issubclass(ConfigurationError, DomainError))
    self.assertTrue(issubclass(ServerNotFoundError, DomainError))
    self.assertTrue(issubclass(InvalidPowerActionError, DomainError))
    self.assertTrue(issubclass(SimulationError, DomainError))
    self.assertTrue(issubclass(DomainError, Exception))

  def test_pterodactyl_api_error_attributes(self):
    err = PterodactylApiError(
        "Server not found", status_code=404, server_id="srv-123", details="Resource missing"
    )
    self.assertEqual(str(err), "Server not found")
    self.assertEqual(err.status_code, 404)
    self.assertEqual(err.server_id, "srv-123")
    self.assertEqual(err.details, "Resource missing")

  def test_steam_api_error_attributes(self):
    err = SteamApiError("Steam API rate limited", app_id="896660")
    self.assertEqual(str(err), "Steam API rate limited")
    self.assertEqual(err.app_id, "896660")
    self.assertEqual(err.status_code, 502)

  def test_a2s_query_error(self):
    err = A2SQueryError("Socket timeout connecting to server")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(str(err), "Socket timeout connecting to server")
    self.assertEqual(err.status_code, 504)

  def test_configuration_error(self):
    err = ConfigurationError("Corrupted config.json format")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(str(err), "Corrupted config.json format")
    self.assertEqual(err.status_code, 400)

  def test_server_not_found_error(self):
    err = ServerNotFoundError("Server 'srv-404' not found in configuration", server_id="srv-404")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 404)
    self.assertEqual(err.server_id, "srv-404")

  def test_invalid_power_action_error(self):
    err = InvalidPowerActionError("Invalid signal 'explode'", action="explode")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 400)
    self.assertEqual(err.action, "explode")

  def test_simulation_error(self):
    err = SimulationError("Simulated build failed", server_id="srv-1")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 400)
    self.assertEqual(err.server_id, "srv-1")


class TestDomainErrorBoundary(unittest.TestCase):

  def test_domain_error_handled_by_fastapi(self):
    client = TestClient(app, raise_server_exceptions=False)

    # Create a test endpoint on the app that raises a DomainError
    @app.get("/test-error-boundary")
    async def trigger_domain_error():
      raise PterodactylApiError("Unauthorized access to panel", status_code=401, server_id="srv-1")

    res = client.get("/test-error-boundary")
    self.assertEqual(res.status_code, 401)
    body = res.json()
    self.assertEqual(body.get("status"), "error")
    self.assertEqual(body.get("error"), "PterodactylApiError")
    self.assertIn("Unauthorized access to panel", body.get("message", ""))

  def test_server_not_found_handled_by_fastapi(self):
    client = TestClient(app, raise_server_exceptions=False)

    @app.get("/test-server-not-found")
    async def trigger_not_found():
      raise ServerNotFoundError("Target server not configured", server_id="unknown")

    res = client.get("/test-server-not-found")
    self.assertEqual(res.status_code, 404)
    body = res.json()
    self.assertEqual(body.get("status"), "error")
    self.assertEqual(body.get("error"), "ServerNotFoundError")
    self.assertEqual(body.get("message"), "Target server not configured")


class TestAdapterTypedReturns(unittest.IsolatedAsyncioTestCase):

  async def test_pterodactyl_adapter_returns_typed_models(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)

    # 1. get_server_name
    mock_client.get.return_value = MagicMock(
        status_code=200, json=lambda: {"attributes": {"name": "Dedicated Box"}}
    )
    name_res = await adapter.get_server_name("http://panel", "key", "srv1")
    self.assertIsInstance(name_res, ServerNameResult)
    self.assertEqual(name_res.name, "Dedicated Box")
    self.assertIsNone(name_res.error)

    # 2. get_server_allocation
    mock_client.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "attributes": {
                "relationships": {
                    "allocations": {
                        "data": [
                            {"attributes": {"is_default": True, "ip": "10.0.0.5", "port": 7777}}
                        ]
                    }
                }
            }
        },
    )
    alloc_res = await adapter.get_server_allocation("http://panel", "key", "srv1")
    self.assertIsInstance(alloc_res, ServerAllocation)
    self.assertEqual(alloc_res.ip, "10.0.0.5")
    self.assertEqual(alloc_res.port, 7777)

    # 3. get_local_build
    mock_client.get.return_value = MagicMock(
        status_code=200, text='"AppState"\n{\n\t"buildid"\t\t"998877"\n}'
    )
    build_res = await adapter.get_local_build("http://panel", "key", "srv1", "steamapps/manifest.acf")
    self.assertIsInstance(build_res, LocalBuildResult)
    self.assertEqual(build_res.build_id, "998877")
    self.assertIsNone(build_res.error)

    # 4. send_power_signal
    mock_client.post.return_value = MagicMock(status_code=204)
    power_res = await adapter.send_power_signal("http://panel", "key", "srv1", "restart")
    self.assertIsInstance(power_res, OperationResult)
    self.assertTrue(power_res.success)
    self.assertIsNone(power_res.error)

    # 5. rename_server
    mock_client.post.return_value = MagicMock(status_code=200)
    rename_res = await adapter.rename_server("http://panel", "key", "srv1", "New Name")
    self.assertIsInstance(rename_res, OperationResult)
    self.assertTrue(rename_res.success)
    self.assertIsNone(rename_res.error)

  async def test_pterodactyl_adapter_raise_on_error(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)

    # Power signal failure with raise_on_error=True
    mock_client.post.return_value = MagicMock(status_code=500, text="Internal Panel Error")
    with self.assertRaises(PterodactylApiError) as ctx:
      await adapter.send_power_signal(
          "http://panel", "key", "srv1", "restart", raise_on_error=True
      )
    self.assertEqual(ctx.exception.server_id, "srv1")
    self.assertEqual(ctx.exception.status_code, 500)

    # get_local_build failure with raise_on_error=True
    mock_client.get.return_value = MagicMock(status_code=404, text="File Not Found")
    with self.assertRaises(PterodactylApiError) as ctx:
      await adapter.get_local_build(
          "http://panel", "key", "srv1", "manifest.acf", raise_on_error=True
      )
    self.assertEqual(ctx.exception.server_id, "srv1")
    self.assertEqual(ctx.exception.status_code, 404)

  async def test_steam_adapter_raise_on_error(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = SteamAdapter(mock_client)

    # SteamCMD API failure with raise_on_error=True
    mock_client.get.return_value = MagicMock(status_code=500, text="Server Error")
    with self.assertRaises(SteamApiError) as ctx:
      await adapter.get_latest_build("896660", raise_on_error=True)
    self.assertEqual(ctx.exception.app_id, "896660")
    self.assertEqual(ctx.exception.status_code, 500)

  async def test_a2s_adapter_returns_player_metrics(self):
    adapter = A2SAdapter()
    metrics = await adapter.get_player_count("", 0)
    self.assertIsInstance(metrics, PlayerMetrics)
    self.assertIsNone(metrics.current)
    self.assertIsNone(metrics.max)


if __name__ == "__main__":
  unittest.main()

