import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.exceptions import ServerNotFoundError
from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    NotificationPreview,
    ServerModel,
    SteamSearchResult,
)
from app.services.preview_store import WebhookPreviewStore
from app.web.schemas import (
    CheckNowResponse,
    ClearBuildResponse,
    LookupNameResponse,
    PowerActionResponse,
    SimulateBuildResponse,
    SingleServerSaveResponse,
    SyncNameResponse,
)
from app.main import app


class TestTypedRouteEndpoints(unittest.TestCase):

  def setUp(self):
    self.client = TestClient(app, raise_server_exceptions=True)
    self.service = MagicMock()
    app.state.server_service = self.service
    self.repo = MagicMock()
    app.state.repo = self.repo
    self.preview_store = WebhookPreviewStore()
    app.state.preview_store = self.preview_store

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

  def test_toggle_test_mode_typed_endpoints(self):
    self.service.toggle_test_mode = AsyncMock(return_value=True)
    res = self.client.post("/api/toggle-test-mode", json={"enabled": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "test_mode": True})

    self.service.toggle_test_mode = AsyncMock(return_value=False)
    res_legacy = self.client.post("/toggle-test-mode", json={"enabled": False})
    self.assertEqual(res_legacy.status_code, 200)
    self.assertEqual(res_legacy.json(), {"status": "ok", "test_mode": False})

  def test_toggle_ssl_verify_typed_endpoints(self):
    self.service.toggle_ssl_verify = AsyncMock(return_value=True)
    res = self.client.post("/api/toggle-ssl-verify", json={"enabled": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "ssl_verify": True})

    self.service.toggle_ssl_verify = AsyncMock(return_value=False)
    res_legacy = self.client.post("/toggle-ssl-verify", json={"enabled": False})
    self.assertEqual(res_legacy.status_code, 200)
    self.assertEqual(res_legacy.json(), {"status": "ok", "ssl_verify": False})

  def test_toggle_ssl_verify_with_real_server_service_no_name_error(self):
    from app.services.server_service import ServerService
    cfg = AppConfigModel(ssl_verify=False)
    self.repo.load.return_value = cfg
    real_service = ServerService(
        repository=self.repo,
        ptero=AsyncMock(),
        steam=AsyncMock(),
        discord=AsyncMock(),
        preview_store=self.preview_store,
        simulator_store=MagicMock(),
        countdown=MagicMock(),
        runtime_state=MagicMock(),
    )
    app.state.server_service = real_service
    res = self.client.post("/api/toggle-ssl-verify", json={"enabled": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "ssl_verify": True})
    self.assertTrue(cfg.ssl_verify)
    self.repo.save.assert_called_with(cfg)

  def test_api_test_webhook_endpoints(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-alpha")
    self.repo.load.return_value = AppConfigModel(servers=[srv])
    self.service.find_server_index.return_value = 0
    self.service.test_webhook = AsyncMock(return_value="Dispatched test webhook")

    # 1. Path param endpoint
    res1 = self.client.post("/api/test/webhook/srv-alpha")
    self.assertEqual(res1.status_code, 200)
    self.assertEqual(res1.json().get("status"), "ok")
    self.assertEqual(res1.json().get("message"), "Dispatched test webhook")
    self.assertEqual(res1.json().get("server_id"), "srv-alpha")

    # 2. Body payload endpoint
    res2 = self.client.post("/api/test/webhook", json={"server_id": "srv-alpha"})
    self.assertEqual(res2.status_code, 200)
    self.assertEqual(res2.json().get("status"), "ok")
    self.assertEqual(res2.json().get("server_id"), "srv-alpha")

  def test_test_webhook_route_redirect_and_json(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-alpha")
    self.repo.load.return_value = AppConfigModel(servers=[srv])
    self.service.find_server_index.return_value = 0
    self.service.test_webhook = AsyncMock(return_value="Dispatched test webhook")

    # JSON accept header
    res_json = self.client.post("/test-webhook/srv-alpha", headers={"accept": "application/json"})
    self.assertEqual(res_json.status_code, 200)
    self.assertEqual(res_json.json().get("status"), "ok")

    # Default form post (follow_redirects=False)
    res_redirect = self.client.post("/test-webhook/srv-alpha", follow_redirects=False)
    self.assertEqual(res_redirect.status_code, 303)
    self.assertEqual(res_redirect.headers.get("location"), "/?toast=test_webhook&open_sim=1")

  def test_test_webhook_end_to_end_with_notification_preview_no_500(self):
    """Verifies that dispatching a test webhook with NotificationPreview does not 500 on dashboard redirect."""
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-alpha")
    cfg = AppConfigModel(panel_url="https://panel.example.com", api_key="secret", servers=[srv], test_mode=True)
    self.repo.load.return_value = cfg
    self.service.find_server_index.return_value = 0

    # Simulate AnnouncementService setting a NotificationPreview in preview_store during test_webhook
    async def fake_test_webhook(ident):
      self.preview_store.set_preview(
          NotificationPreview(
              server_name="Valheim Dedicated",
              message="Update Available: 12345",
              timestamp="12:22 PM",
              embed={"title": "Patch Notes", "description": "Bug fixes"},
          )
      )
      return "Alert simulated"

    self.service.test_webhook = AsyncMock(side_effect=fake_test_webhook)

    # When following the 303 redirect to GET /, dashboard renders cleanly with 200 OK
    res = self.client.post("/test-webhook/srv-alpha", follow_redirects=True)
    self.assertEqual(res.status_code, 200)
    self.assertIn("Valheim Dedicated", res.text)
    self.assertIn("Update Available: 12345", res.text)

  def test_toggle_server_setting_with_server_idx_fallback(self):
    self.service.update_server_toggle.side_effect = [
        ServerNotFoundError("unknown-sid"),
        None,
    ]
    res = self.client.post(
        "/api/servers/unknown-sid/toggle",
        json={"field": "auto_restart", "value": True, "server_idx": 0},
    )
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "field": "auto_restart", "value": True})
    self.assertEqual(self.service.update_server_toggle.call_count, 2)

  def test_fastapi_route_response_model_annotations(self):
    route_models = {}
    for r in app.routes:
      if hasattr(r, "path") and hasattr(r, "response_model"):
        methods = tuple(r.methods) if hasattr(r, "methods") else ()
        route_models[(r.path, methods)] = r.response_model

    self.assertIn(("/api/servers/detect-details", ("GET",)), route_models)
    self.assertIs(route_models[("/api/servers/detect-details", ("GET",))], DetectedServerDetails)

    self.assertIn(("/api/servers/lookup-name", ("GET",)), route_models)
    self.assertIs(route_models[("/api/servers/lookup-name", ("GET",))], LookupNameResponse)

    self.assertIn(("/api/steam/search", ("GET",)), route_models)
    self.assertEqual(route_models[("/api/steam/search", ("GET",))], list[SteamSearchResult])

    self.assertIn(("/api/servers/{server_id}/power/{action}", ("POST",)), route_models)
    self.assertIs(route_models[("/api/servers/{server_id}/power/{action}", ("POST",))], PowerActionResponse)

    self.assertIn(("/api/check-now", ("POST",)), route_models)
    self.assertIs(route_models[("/api/check-now", ("POST",))], CheckNowResponse)

    self.assertIn(("/api/test/simulate-build", ("POST",)), route_models)
    self.assertIs(route_models[("/api/test/simulate-build", ("POST",))], SimulateBuildResponse)

    self.assertIn(("/api/test/clear-build", ("POST",)), route_models)
    self.assertIs(route_models[("/api/test/clear-build", ("POST",))], ClearBuildResponse)

    self.assertIn(("/api/servers/{server_id}/sync-name", ("POST",)), route_models)
    self.assertIs(route_models[("/api/servers/{server_id}/sync-name", ("POST",))], SyncNameResponse)

    self.assertIn(("/api/servers/{server_id}/save", ("POST",)), route_models)
    self.assertIs(route_models[("/api/servers/{server_id}/save", ("POST",))], SingleServerSaveResponse)

  def test_endpoint_responses_satisfy_schemas(self):
    self.repo.load.return_value = AppConfigModel(
        panel_url="https://panel.test",
        api_key="key",
        servers=[ServerModel(server_id="srv-1", name="Test Server")],
    )
    self.service.find_server_index.return_value = 0
    self.service.lookup_server_name = AsyncMock(return_value="Terraria Server")
    self.service.detect_server_details = AsyncMock(
        return_value=DetectedServerDetails(name="Terraria", app_id="105600", manifest_path="appmanifest_105600.acf", detected=True)
    )
    self.service.search_steam_games = AsyncMock(
        return_value=[SteamSearchResult(app_id="105600", name="Terraria", type="game")]
    )
    self.service.send_power_action = AsyncMock(return_value=(True, None))

    # 1. Lookup Name
    res = self.client.get("/api/servers/lookup-name?server_id=srv-1")
    self.assertEqual(res.status_code, 200)
    validated_lookup = LookupNameResponse.model_validate(res.json())
    self.assertEqual(validated_lookup.name, "Terraria Server")
    self.assertEqual(validated_lookup.status, "ok")

    # 2. Detect Details
    res = self.client.get("/api/servers/detect-details?server_id=srv-1")
    self.assertEqual(res.status_code, 200)
    details_data = res.json().get("details")
    validated_details = DetectedServerDetails.model_validate(details_data)
    self.assertEqual(validated_details.app_id, "105600")

    # 3. Steam Search
    res = self.client.get("/api/steam/search?q=terraria")
    self.assertEqual(res.status_code, 200)
    results_data = res.json().get("results")
    self.assertIsInstance(results_data, list)
    validated_search = [SteamSearchResult.model_validate(item) for item in results_data]
    self.assertEqual(len(validated_search), 1)
    self.assertEqual(validated_search[0].app_id, "105600")

    # 4. Power Action
    res = self.client.post("/api/servers/srv-1/power/restart")
    self.assertEqual(res.status_code, 200)
    validated_power = PowerActionResponse.model_validate(res.json())
    self.assertEqual(validated_power.status, "ok")
    self.assertEqual(validated_power.server_id, "srv-1")
    self.assertEqual(validated_power.action, "restart")


if __name__ == "__main__":
  unittest.main()

