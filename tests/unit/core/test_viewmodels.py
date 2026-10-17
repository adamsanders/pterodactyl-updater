import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    ServerModel,
    ServerRuntimeState,
    ServerUpdateStatus,
    SteamSearchResult,
)
from app.main import app
from app.web.schemas import (
    DashboardViewModel,
    LookupNameResponse,
    PowerActionResponse,
    ServerCardViewModel,
    SettingsUpdateDTO,
    SimulateBuildRequest,
    SingleServerSaveRequest,
    SyncNameRequest,
    WebhookPreview,
)


class TestPresentationViewModels(unittest.TestCase):
  """Unit tests for ServerCardViewModel and DashboardViewModel."""

  def test_server_card_view_model_attributes_and_dict_access(self):
    vm = ServerCardViewModel(
        card_index=0,
        server_id="srv-alpha",
        name="Alpha",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
        query_port_offset=2,
        broadcast_command_template="say {message}",
        auto_restart=True,
        discord_alerts=True,
        warn_ingame_countdown=True,
        warn_discord_countdown=False,
        current_build="1000",
        latest_build="2000",
        status="Update Available",
        countdown_remaining=120,
        countdown_target=1770000120,
    )

    # Attribute access
    self.assertEqual(vm.card_index, 0)
    self.assertEqual(vm.server_id, "srv-alpha")
    self.assertEqual(vm.name, "Alpha")
    self.assertEqual(vm.query_port_offset, 2)
    self.assertTrue(vm.auto_restart)
    self.assertEqual(vm.current_build, "1000")
    self.assertEqual(vm.latest_build, "2000")
    self.assertEqual(vm.status, "Update Available")
    self.assertEqual(vm.last_status, "Update Available")
    self.assertEqual(vm.idx, 0)

    # Dict-like access (__getitem__, .get, __contains__)
    self.assertEqual(vm["name"], "Alpha")
    self.assertEqual(vm["server_id"], "srv-alpha")
    self.assertEqual(vm.get("query_port_offset"), 2)
    self.assertEqual(vm.get("nonexistent", "default"), "default")
    self.assertIn("name", vm)
    self.assertIn("server_id", vm)

  def test_server_card_view_model_from_domain_with_runtime_state(self):
    server = ServerModel(
        server_id="srv-1",
        name="Terraria",
        app_id="105600",
        manifest_path="steamapps/appmanifest_105600.acf",
    )
    rt = ServerRuntimeState(
        server_id="srv-1",
        current_build="500",
        latest_build="600",
        last_status="Restarting",
    )
    vm = ServerCardViewModel.from_domain(
        server=server,
        card_index=0,
        runtime_state=rt,
        countdown_remaining=60,
        countdown_target=1770000060,
    )

    self.assertEqual(vm.server_id, "srv-1")
    self.assertEqual(vm.name, "Terraria")
    self.assertEqual(vm.current_build, "500")
    self.assertEqual(vm.latest_build, "600")
    self.assertEqual(vm.status, "Restarting")
    self.assertEqual(vm.countdown_remaining, 60)
    self.assertEqual(vm.countdown_target, 1770000060)

  def test_dashboard_view_model_attributes_and_dict_access(self):
    card_vm = ServerCardViewModel(
        card_index=0,
        server_id="srv-1",
        name="Test Server",
    )
    dvm = DashboardViewModel(
        panel_url="https://panel.example.com",
        api_key="api-key",
        check_interval=10,
        discord_webhook="https://discord.com/hook",
        test_mode=True,
        ssl_verify=False,
        last_check="2026-10-17 12:00:00",
        servers=[card_vm],
        app_version="1.27.0",
        commit_code="abcdef1",
        preview=WebhookPreview(
            server_name="Test Server",
            message="Test message",
            timestamp="12:00",
        ),
    )

    # Attribute access
    self.assertEqual(dvm.panel_url, "https://panel.example.com")
    self.assertEqual(dvm.check_interval, 10)
    self.assertTrue(dvm.test_mode)
    self.assertEqual(dvm.version, "1.27.0")
    self.assertEqual(len(dvm.servers), 1)
    self.assertEqual(dvm.preview.server_name, "Test Server")

    # Dict-like access
    self.assertEqual(dvm["panel_url"], "https://panel.example.com")
    self.assertEqual(dvm.get("check_interval"), 10)
    self.assertIn("discord_webhook", dvm)

  def test_dashboard_view_model_from_domain(self):
    cfg = AppConfigModel(
        panel_url="https://panel.domain.com",
        api_key="secret",
        check_interval=5,
        servers=[
            ServerModel(server_id="srv-a", name="Server A"),
            ServerModel(server_id="srv-b", name="Server B"),
        ],
    )
    runtime_states = {
        "srv-a": ServerRuntimeState(server_id="srv-a", current_build="10", latest_build="10"),
        "srv-b": ServerRuntimeState(server_id="srv-b", current_build="10", latest_build="20", last_status="Update Available"),
    }
    countdown = MagicMock()
    countdown.get_remaining.side_effect = lambda sid: 180 if sid == "srv-b" else 0
    countdown.get_target.side_effect = lambda sid: 1770000180 if sid == "srv-b" else 0

    dvm = DashboardViewModel.from_domain(
        config=cfg,
        runtime_states=runtime_states,
        countdown=countdown,
        last_check="2026-10-17 14:00:00",
        app_version="1.27.0",
        commit_code="1234567",
    )

    self.assertEqual(len(dvm.servers), 2)
    self.assertEqual(dvm.servers[0].server_id, "srv-a")
    self.assertEqual(dvm.servers[0].current_build, "10")
    self.assertEqual(dvm.servers[1].server_id, "srv-b")
    self.assertEqual(dvm.servers[1].current_build, "10")
    self.assertEqual(dvm.servers[1].latest_build, "20")
    self.assertEqual(dvm.servers[1].countdown_remaining, 180)
    self.assertEqual(dvm.last_check, "2026-10-17 14:00:00")

  def test_view_models_dictionary_iteration_methods(self):
    vm = ServerCardViewModel(card_index=0, server_id="srv-1", name="Alpha")
    dvm = DashboardViewModel(panel_url="https://panel.test", servers=[vm])

    # ServerCardViewModel dict protocols
    vm_dict = dict(vm)
    self.assertIsInstance(vm_dict, dict)
    self.assertEqual(vm_dict["name"], "Alpha")
    self.assertIn("server_id", vm.keys())
    self.assertIn("Alpha", list(vm.values()))
    self.assertIn(("card_index", 0), list(vm.items()))
    self.assertIn("name", list(iter(vm)))

    # DashboardViewModel dict protocols
    dvm_dict = dict(dvm)
    self.assertIsInstance(dvm_dict, dict)
    self.assertEqual(dvm_dict["panel_url"], "https://panel.test")
    self.assertIn("panel_url", dvm.keys())
    self.assertIn("https://panel.test", list(dvm.values()))
    self.assertIn("panel_url", list(iter(dvm)))

  def test_dashboard_view_model_from_domain_case_insensitive_runtime_state(self):
    cfg = AppConfigModel(servers=[ServerModel(server_id="SRV-VALHEIM", name="Valheim")])
    runtime_states = {
        "srv-valheim": ServerRuntimeState(
            server_id="srv-valheim",
            current_build="999",
            latest_build="1000",
            last_status="Update Available",
        )
    }
    dvm = DashboardViewModel.from_domain(config=cfg, runtime_states=runtime_states)
    self.assertEqual(dvm.servers[0].current_build, "999")
    self.assertEqual(dvm.servers[0].latest_build, "1000")
    self.assertEqual(dvm.servers[0].status, "Update Available")

  def test_server_card_template_renders_directly_with_view_model(self):
    from app.web.templating import templates
    vm = ServerCardViewModel(
        card_index=0,
        server_id="srv-1",
        name="Solo ViewModel Server",
        status="Update Available",
        current_build="100",
        latest_build="200",
        countdown_remaining=120,
        countdown_target=1770000120,
    )
    tpl = templates.get_template("components/_server_card.html")
    html = tpl.render(srv=vm)
    self.assertIn("Solo ViewModel Server", html)
    self.assertIn("Update Available", html)
    self.assertIn("100 &rarr; 200", html)
    self.assertIn("2m 0s", html)


class TestTypedRouteSchemas(unittest.TestCase):

  def test_simulate_build_request_schema(self):
    req = SimulateBuildRequest(build_id="12345")
    self.assertEqual(req.build_id, "12345")
    self.assertIsNone(req.server_id)
    self.assertEqual(req.server_idx, 0)

    req2 = SimulateBuildRequest(build_id="67890", server_id="srv-alpha", server_idx=1)
    self.assertEqual(req2.build_id, "67890")
    self.assertEqual(req2.server_id, "srv-alpha")
    self.assertEqual(req2.server_idx, 1)

  def test_sync_name_request_schema(self):
    req = SyncNameRequest(server_id="srv-100")
    self.assertEqual(req.server_id, "srv-100")

  def test_single_server_save_request_schema(self):
    req = SingleServerSaveRequest(
        name="Valheim Box",
        server_id="srv-v",
        app_id="896660",
        manifest_path="steamapps/manifest.acf",
        query_port_offset=1,
    )
    self.assertEqual(req.name, "Valheim Box")
    self.assertEqual(req.server_id, "srv-v")
    self.assertEqual(req.app_id, "896660")
    self.assertEqual(req.manifest_path, "steamapps/manifest.acf")
    self.assertEqual(req.query_port_offset, 1)


class TestWebDTORelocationAndReExports(unittest.TestCase):
  """Verifies web DTOs live in app.web.schemas and inherit from domain commands, with no circular imports in app.core.models."""

  def test_web_dto_classes_in_web_schemas(self):
    from app.core.models import NotificationPreview, SaveServerCommand, SaveSettingsCommand
    self.assertTrue(issubclass(SingleServerSaveRequest, SaveServerCommand))
    self.assertTrue(issubclass(SettingsUpdateDTO, SaveSettingsCommand))
    self.assertTrue(issubclass(WebhookPreview, NotificationPreview))

  def test_core_models_does_not_forward_web_schemas(self):
    import app.core.models as core_models

    with self.assertRaises(AttributeError):
      _ = core_models.SingleServerSaveRequest
    with self.assertRaises(AttributeError):
      _ = core_models.SettingsUpdateDTO
    with self.assertRaises(AttributeError):
      _ = core_models.WebhookPreview

  def test_core_models_exports_domain_commands(self):
    import app.core.models as core_models

    dir_entries = dir(core_models)
    self.assertIn("SaveServerCommand", dir_entries)
    self.assertIn("SaveSettingsCommand", dir_entries)
    self.assertIn("NotificationPreview", dir_entries)
    self.assertNotIn("SingleServerSaveRequest", dir_entries)
    self.assertNotIn("SettingsUpdateDTO", dir_entries)


class TestTemplateRendering(unittest.TestCase):

  def test_global_status_template_renders_live_last_check(self):
    from app.web.templating import templates
    cfg = AppConfigModel()
    rendered = templates.get_template("components/_global_status.html").render({
        "cfg": cfg,
        "last_check": "2026-10-16 19:30:00",
    })
    self.assertIn("2026-10-16 19:30:00", rendered)
    self.assertNotIn(">Never<", rendered)

  def test_server_card_template_renders_builds_from_runtime_states(self):
    from app.web.templating import templates
    srv = ServerModel(server_id="srv-val", name="Valheim")
    cfg = AppConfigModel(servers=[srv])
    runtime_states = {
        "srv-val": ServerRuntimeState(
            server_id="srv-val",
            current_build="999000",
            latest_build="999000",
            last_status=ServerUpdateStatus.UP_TO_DATE,
        )
    }
    rendered = templates.get_template("components/_server_card.html").render({
        "cfg": cfg,
        "srv": srv,
        "idx": 0,
        "srv_id": "srv-val",
        "runtime_states": runtime_states,
    })
    self.assertIn("Build:", rendered)
    self.assertIn("999000", rendered)


class TestStronglyTypedRouteResponses(unittest.TestCase):
  """Unit tests verifying strongly typed route response schemas and annotations."""

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

  def test_lookup_name_response_model(self):
    resp = LookupNameResponse(name="Valheim Dedicated Server")
    self.assertEqual(resp.name, "Valheim Dedicated Server")
    self.assertTrue(resp.success)
    self.assertEqual(resp.status, "ok")
    data = resp.model_dump()
    self.assertEqual(data["name"], "Valheim Dedicated Server")
    self.assertEqual(data["status"], "ok")

  def test_power_action_response_model(self):
    resp = PowerActionResponse(
        status="ok",
        server_id="srv-valheim",
        action="restart",
        effective_state="starting",
    )
    self.assertEqual(resp.status, "ok")
    self.assertEqual(resp.server_id, "srv-valheim")
    self.assertEqual(resp.action, "restart")
    self.assertEqual(resp.effective_state, "starting")

  def test_endpoint_responses_satisfy_schemas(self):
    app.state.repo = MagicMock()
    app.state.repo.load.return_value = AppConfigModel(
        panel_url="https://panel.test",
        api_key="key",
        servers=[ServerModel(server_id="srv-1", name="Test Server")],
    )
    app.state.server_service = MagicMock()
    app.state.server_service.find_server_index.return_value = 0
    app.state.server_service.lookup_server_name = AsyncMock(return_value="Terraria Server")
    app.state.server_service.detect_server_details = AsyncMock(
        return_value=DetectedServerDetails(name="Terraria", app_id="105600", manifest_path="appmanifest_105600.acf", detected=True)
    )
    app.state.server_service.search_steam_games = AsyncMock(
        return_value=[SteamSearchResult(app_id="105600", name="Terraria", type="game")]
    )
    app.state.server_service.send_power_action = AsyncMock(return_value=(True, None))

    client = TestClient(app, raise_server_exceptions=True)

    # 1. Lookup Name
    res = client.get("/api/servers/lookup-name?server_id=srv-1")
    self.assertEqual(res.status_code, 200)
    validated_lookup = LookupNameResponse.model_validate(res.json())
    self.assertEqual(validated_lookup.name, "Terraria Server")
    self.assertEqual(validated_lookup.status, "ok")

    # 2. Detect Details
    res = client.get("/api/servers/detect-details?server_id=srv-1")
    self.assertEqual(res.status_code, 200)
    details_data = res.json().get("details")
    validated_details = DetectedServerDetails.model_validate(details_data)
    self.assertEqual(validated_details.app_id, "105600")

    # 3. Steam Search
    res = client.get("/api/steam/search?q=terraria")
    self.assertEqual(res.status_code, 200)
    results_data = res.json().get("results")
    self.assertIsInstance(results_data, list)
    validated_search = [SteamSearchResult.model_validate(item) for item in results_data]
    self.assertEqual(len(validated_search), 1)
    self.assertEqual(validated_search[0].app_id, "105600")

    # 4. Power Action
    res = client.post("/api/servers/srv-1/power/restart")
    self.assertEqual(res.status_code, 200)
    validated_power = PowerActionResponse.model_validate(res.json())
    self.assertEqual(validated_power.status, "ok")
    self.assertEqual(validated_power.server_id, "srv-1")
    self.assertEqual(validated_power.action, "restart")


if __name__ == "__main__":
  unittest.main()
