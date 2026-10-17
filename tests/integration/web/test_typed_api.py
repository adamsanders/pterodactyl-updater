import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.models import ServerModel
from app.main import app


class TestTypedRouteEndpoints(unittest.TestCase):

  def setUp(self):
    self.client = TestClient(app, raise_server_exceptions=True)
    self.service = MagicMock()
    app.state.server_service = self.service

  def test_simulate_build_typed_endpoint_success(self):
    self.service.trigger_simulated_build = AsyncMock(return_value="srv-alpha")
    res = self.client.post(
        "/api/test/simulate-build",
        json={"build_id": "88888", "server_id": "srv-alpha"},
    )
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server_id"), "srv-alpha")
    self.assertEqual(data.get("simulated_build"), "88888")
    self.assertEqual(data.get("build_id"), "88888")
    self.service.trigger_simulated_build.assert_called_once_with("srv-alpha", "88888")

  def test_simulate_build_typed_endpoint_validation_error(self):
    # Missing required build_id
    res = self.client.post("/api/test/simulate-build", json={"server_id": "srv-alpha"})
    self.assertEqual(res.status_code, 422)

  def test_sync_name_typed_endpoint_success(self):
    self.service.sync_server_name = AsyncMock(return_value="Synced Box")
    res = self.client.post(
        "/api/servers/srv-beta/sync-name",
        json={"server_id": "srv-beta"},
    )
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("name"), "Synced Box")
    self.assertEqual(data.get("server_id"), "srv-beta")
    self.assertTrue(data.get("success"))
    self.service.sync_server_name.assert_called_once_with("srv-beta", server_id_override="srv-beta")

  def test_save_single_server_typed_endpoint_success(self):
    saved_srv = ServerModel(
        name="Updated Valheim",
        server_id="srv-v",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
        query_port_offset=2,
    )
    self.service.save_single_server = AsyncMock(return_value=saved_srv)

    payload = {
        "name": "Updated Valheim",
        "server_id": "srv-v",
        "app_id": "896660",
        "manifest_path": "steamapps/appmanifest_896660.acf",
        "query_port_offset": 2,
    }
    res = self.client.post("/api/servers/srv-v/save", json=payload)
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server_id"), "srv-v")
    self.assertEqual(data.get("server", {}).get("name"), "Updated Valheim")
    self.assertEqual(data.get("server", {}).get("query_port_offset"), 2)

  def test_check_now_typed_endpoint_success(self):
    self.service.trigger_immediate_check = AsyncMock()
    res = self.client.post("/api/check-now")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("message"), "Update check initiated")
    self.service.trigger_immediate_check.assert_called_once()

  def test_clear_build_typed_endpoint_success(self):
    self.service.clear_simulated_build = MagicMock(return_value="srv-alpha")
    res = self.client.post(
        "/api/test/clear-build",
        json={"server_id": "srv-alpha"},
    )
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server_id"), "srv-alpha")
    self.service.clear_simulated_build.assert_called_once_with("srv-alpha")

  def test_clear_build_all_typed_endpoint_success(self):
    self.service.clear_simulated_build = MagicMock(return_value=None)
    res = self.client.post("/api/test/clear-build")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server_id"), "")
    self.service.clear_simulated_build.assert_called_once_with(None)


if __name__ == "__main__":
  unittest.main()
