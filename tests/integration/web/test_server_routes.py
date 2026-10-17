import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.exceptions import SimulationError
from app.core.models import AppConfigModel, OperationResult, ServerModel
from app.main import app
from app.web.dependencies import get_service


class TestServerIdRouteIntegration(unittest.TestCase):

  def setUp(self):
    self.app = app
    self.client = TestClient(self.app, raise_server_exceptions=True)
    self.app.state.repo = MagicMock()
    self.app.state.repo.load.return_value = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        test_mode=True,
        servers=[
            ServerModel(name="SrvAlpha", server_id="srv-alpha"),
            ServerModel(name="SrvBeta", server_id="srv-beta"),
        ],
    )
    self.app.state.server_service = MagicMock()
    self.app.state.orchestrator = MagicMock()
    self.app.state.countdown = MagicMock()
    self.app.state.countdown.get_remaining.return_value = 0
    self.app.state.countdown.get_target.return_value = 0.0
    self.app.state.countdown.is_running.return_value = False
    self.app.state.preview_store = MagicMock()
    self.app.state.preview_store.get_preview.return_value = None
    self.app.state.ptero = AsyncMock()
    self.app.state.ptero.get_external_ip.return_value = "1.2.3.4"
    self.app.state.ptero.get_power_state.return_value = "running"
    self.app.state.ptero.consume_startup_transition.return_value = False
    self.app.state.ptero.get_server_allocation.return_value = ("1.2.3.4", 2456)
    self.app.state.a2s = AsyncMock()
    self.app.state.a2s.get_player_count.return_value = (0, 10)
    self.app.state.call_tracker = MagicMock()

  def test_power_action_route_with_server_id(self):
    self.app.state.server_service.find_server_index.return_value = 1
    self.app.state.server_service.send_power_action = AsyncMock(return_value=(True, None))

    res = self.client.post("/api/servers/srv-beta/power/restart")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server_id"), "srv-beta")
    self.app.state.server_service.send_power_action.assert_called_once_with("srv-beta", "restart")

  def test_power_action_route_legacy_index_fallback(self):
    self.app.state.server_service.find_server_index.return_value = 0
    self.app.state.server_service.send_power_action = AsyncMock(return_value=(True, None))

    res = self.client.post("/api/servers/0/power/start")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.app.state.server_service.send_power_action.assert_called_once_with("0", "start")

  def test_simulate_build_route_accepts_server_id(self):
    self.app.state.server_service.trigger_simulated_build = AsyncMock(return_value="srv-beta")

    res = self.client.post(
        "/api/test/simulate-build",
        json={"server_id": "srv-beta", "build_id": "777777"},
    )
    self.assertEqual(res.status_code, 200)
    self.app.state.server_service.trigger_simulated_build.assert_called_once_with("srv-beta", "777777")

  def test_power_action_route_invalid_action_bubbles_error(self):
    self.app.state.server_service.find_server_index.return_value = 1
    self.app.state.server_service.send_power_action = AsyncMock(
        return_value=OperationResult(
            False,
            "Invalid power action 'kaboom'.",
            status_code=400,
            error_type="InvalidPowerAction",
        )
    )
    res = self.client.post("/api/servers/srv-beta/power/kaboom")
    self.assertEqual(res.status_code, 400)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "InvalidPowerActionError")
    self.assertIn("Invalid power action 'kaboom'", data.get("message", ""))

  def test_power_action_route_failure_bubbles_pterodactyl_error(self):
    self.app.state.server_service.send_power_action = AsyncMock(
        return_value=OperationResult(
            False,
            "Panel HTTP 500: Node offline",
            status_code=500,
            error_type="HttpError",
        )
    )
    res = self.client.post("/api/servers/srv-beta/power/restart")
    self.assertEqual(res.status_code, 500)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "PterodactylApiError")
    self.assertIn("Panel HTTP 500", data.get("message", ""))

  def test_simulate_build_failure_bubbles_simulation_error(self):
    self.app.state.server_service.trigger_simulated_build = AsyncMock(
        side_effect=SimulationError("Failed to simulate build update: Target server missing")
    )
    res = self.client.post(
        "/api/test/simulate-build",
        json={"server_id": "srv-nonexistent", "build_id": "111222"},
    )
    self.assertEqual(res.status_code, 400)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "SimulationError")
    self.assertIn("Target server missing", data.get("message", ""))

  def test_rename_server_empty_name_raises_configuration_error(self):
    self.app.state.server_service.find_server_index.return_value = 1
    res = self.client.post(
        "/rename-server/srv-beta",
        data={"srv_name_srv-beta": "   "},
    )
    self.assertEqual(res.status_code, 400)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "ConfigurationError")
    self.assertIn("Server name cannot be empty", data.get("message", ""))

  def test_rename_server_not_found_raises_server_not_found_error(self):
    self.app.state.server_service.find_server_index.return_value = None
    res = self.client.post(
        "/rename-server/srv-unknown",
        data={"srv_name_srv-unknown": "New Name"},
    )
    self.assertEqual(res.status_code, 404)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "ServerNotFoundError")
    self.assertIn("srv-unknown", data.get("message", ""))


class TestRouteIsolationAndDependencyInjection(unittest.TestCase):

  def setUp(self):
    self.app = app
    self.mock_service = MagicMock()
    self.app.dependency_overrides[get_service] = lambda: self.mock_service
    self.client = TestClient(self.app, raise_server_exceptions=True)

  def tearDown(self):
    self.app.dependency_overrides.clear()

  def test_check_now_delegates_to_service(self):
    self.mock_service.trigger_immediate_check = AsyncMock()
    res = self.client.post("/check-now", headers={"accept": "application/json"})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok"})
    self.mock_service.trigger_immediate_check.assert_called_once()

  def test_toggle_test_mode_delegates_to_service(self):
    self.mock_service.toggle_test_mode = AsyncMock(return_value=True)
    res = self.client.post("/toggle-test-mode", json={"enabled": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "test_mode": True})
    self.mock_service.toggle_test_mode.assert_called_once_with(True)

  def test_lookup_name_route(self):
    self.mock_service.lookup_server_name = AsyncMock(return_value="Terraria Server")
    res = self.client.get("/api/servers/lookup-name?server_id=srv-terra")
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "name": "Terraria Server"})
    self.mock_service.lookup_server_name.assert_called_once_with("srv-terra")

  def test_sync_name_route(self):
    self.mock_service.sync_server_name = AsyncMock(return_value="Synced Server Name")
    res = self.client.post("/api/servers/srv-beta/sync-name", json={"server_id": "srv-beta"})
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("name"), "Synced Server Name")
    self.assertEqual(data.get("server_id"), "srv-beta")
    self.assertTrue(data.get("success"))
    self.mock_service.sync_server_name.assert_called_once_with("srv-beta", server_id_override="srv-beta")

  def test_toggle_server_setting_route(self):
    self.mock_service.update_server_toggle = MagicMock()
    res = self.client.post("/api/servers/srv-beta/toggle", json={"field": "auto_restart", "value": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "field": "auto_restart", "value": True})
    self.mock_service.update_server_toggle.assert_called_once_with("srv-beta", "auto_restart", True)

  def test_save_single_server_route(self):
    saved_model = ServerModel(name="Saved Server", server_id="srv-beta", app_id="123", manifest_path="test.acf", query_port_offset=3)
    self.mock_service.save_single_server = AsyncMock(return_value=saved_model)
    res = self.client.post(
        "/api/servers/srv-beta/save",
        json={"name": "Saved Server", "server_id": "srv-beta", "app_id": "123", "manifest_path": "test.acf", "query_port_offset": 3}
    )
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json().get("status"), "ok")
    self.assertEqual(res.json().get("server", {}).get("name"), "Saved Server")
    self.assertEqual(res.json().get("server", {}).get("query_port_offset"), 3)

  def test_detect_details_route(self):
    self.mock_service.detect_server_details = AsyncMock(
        return_value={"name": "Enshrouded", "app_id": "2230650", "manifest_path": "steamapps/appmanifest_2230650.acf"}
    )
    res = self.client.get("/api/servers/detect-details?server_id=srv-enshrouded")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("details", {}).get("app_id"), "2230650")
    self.mock_service.detect_server_details.assert_called_once_with("srv-enshrouded")

  def test_steam_search_route(self):
    self.mock_service.search_steam_games = AsyncMock(
        return_value=[{"app_id": "2230650", "name": "Enshrouded", "type": "dedicated_server"}]
    )
    res = self.client.get("/api/steam/search?q=enshrouded")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(len(data.get("results", [])), 1)
    self.mock_service.search_steam_games.assert_called_once_with("enshrouded")

  def test_save_settings_route_with_ssl_verify_enabled(self):
    self.app.state.repo = MagicMock()
    self.app.state.repo.load.return_value = AppConfigModel(servers=[])
    res = self.client.post(
        "/save",
        data={
            "panel_url": "https://pterodactyl.example.com",
            "api_key": "ptlc_secret123",
            "check_interval": "10",
            "discord_webhook": "https://discord.com/webhook",
            "ssl_verify": "true",
        },
        follow_redirects=False,
    )
    self.assertEqual(res.status_code, 303)
    self.assertEqual(res.headers["location"], "/?toast=saved")
    self.mock_service.save_settings.assert_called_once()
    dto = self.mock_service.save_settings.call_args[0][0]
    self.assertTrue(dto.ssl_verify)
    self.assertEqual(dto.panel_url, "https://pterodactyl.example.com")

  def test_save_settings_route_with_ssl_verify_omitted_or_disabled(self):
    self.app.state.repo = MagicMock()
    self.app.state.repo.load.return_value = AppConfigModel(servers=[])
    res = self.client.post(
        "/save",
        data={
            "panel_url": "https://pterodactyl.example.com",
            "api_key": "ptlc_secret123",
            "check_interval": "10",
            "discord_webhook": "",
            # ssl_verify omitted like an unchecked checkbox
        },
        follow_redirects=False,
    )
    self.assertEqual(res.status_code, 303)
    self.assertEqual(res.headers["location"], "/?toast=saved")
    self.mock_service.save_settings.assert_called_once()
    dto = self.mock_service.save_settings.call_args[0][0]
    self.assertFalse(dto.ssl_verify)


  def test_simulated_steam_adapter_resolves_route_search(self):
    from app.adapters.simulated_steam import SimulatedSteamAdapter
    from app.services.server_service import ServerService

    mock_real = AsyncMock()
    mock_real.search_games.return_value = [{"app_id": "2278520", "name": "Enshrouded"}]
    mock_store = MagicMock()
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel()

    simulated = SimulatedSteamAdapter(
        real_steam=mock_real,
        simulator_store=mock_store,
        repository=mock_repo,
    )
    real_service = ServerService(
        repository=mock_repo,
        ptero=AsyncMock(),
        steam=simulated,
        announcements=MagicMock(),
        countdown=MagicMock(),
        simulator_store=mock_store,
    )
    self.app.dependency_overrides[get_service] = lambda: real_service

    res = self.client.get("/api/steam/search?q=enshrouded")
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data["status"], "ok")
    self.assertEqual(data["results"], [{"app_id": "2278520", "name": "Enshrouded"}])


if __name__ == "__main__":
  unittest.main()

