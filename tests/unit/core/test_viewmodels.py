import unittest
import warnings
from unittest.mock import MagicMock

from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    NotificationPreview,
    ServerModel,
    ServerRuntimeState,
    ServerUpdateStatus,
    SteamSearchResult,
)
from app.web.schemas import (
    CheckNowResponse,
    ClearBuildResponse,
    DashboardViewModel,
    LookupNameResponse,
    PowerActionResponse,
    ServerCardViewModel,
    SettingsUpdateDTO,
    SimulateBuildRequest,
    SimulateBuildResponse,
    SingleServerSaveRequest,
    SingleServerSaveResponse,
    SyncNameRequest,
    SyncNameResponse,
    TestWebhookRequest,
    TestWebhookResponse,
    ToggleSslVerifyRequest,
    ToggleSslVerifyResponse,
    ToggleTestModeRequest,
    ToggleTestModeResponse,
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

  def test_settings_update_dto_preserves_query_port_offset(self):
    dto = SettingsUpdateDTO(
        servers=[
            ServerModel(name="Srv 1", query_port_offset=0),
            ServerModel(name="Srv 2", query_port_offset=15),
        ]
    )
    self.assertEqual(dto.servers[0].query_port_offset, 0)
    self.assertEqual(dto.servers[1].query_port_offset, 15)
    dumped = dto.model_dump()
    self.assertEqual(dumped["servers"][0]["query_port_offset"], 0)
    self.assertEqual(dumped["servers"][1]["query_port_offset"], 15)

  def test_settings_update_dto_ssl_verify_default_and_custom(self):
    dto_default = SettingsUpdateDTO()
    self.assertFalse(dto_default.ssl_verify)

    dto_verified = SettingsUpdateDTO(ssl_verify=True)
    self.assertTrue(dto_verified.ssl_verify)

    dumped = dto_verified.model_dump()
    self.assertIn("ssl_verify", dumped)
    self.assertIs(dumped["ssl_verify"], True)

    restored = SettingsUpdateDTO.model_validate({"ssl_verify": True})
    self.assertTrue(restored.ssl_verify)


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




class TestStronglyTypedRouteResponses(unittest.TestCase):
  """Unit tests verifying strongly typed route response schemas."""

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

  def test_milestone13_viewmodel_properties_completeness(self):
    vm_matching = ServerCardViewModel(
        card_index=0,
        server_id="srv-1",
        name="Valheim",
        current_build="12345",
        latest_build="12345",
        status="Idle",
        countdown_remaining=125,
    )
    self.assertTrue(vm_matching.is_matching_build)
    self.assertFalse(vm_matching.has_differing_builds)
    self.assertEqual(vm_matching.build_display, "12345")
    self.assertEqual(vm_matching.formatted_countdown, "2m 5s")
    self.assertEqual(vm_matching._ephemeral_current_build, "12345")
    self.assertEqual(vm_matching._ephemeral_latest_build, "12345")
    self.assertEqual(vm_matching._ephemeral_last_status, "Idle")

    vm_differing = ServerCardViewModel(
        card_index=1,
        server_id="srv-2",
        name="Palworld",
        current_build="100",
        latest_build="200",
        status="Update Available",
        countdown_remaining=0,
    )
    self.assertFalse(vm_differing.is_matching_build)
    self.assertTrue(vm_differing.has_differing_builds)
    self.assertEqual(vm_differing.build_display, "100 &rarr; 200")
    self.assertEqual(vm_differing.formatted_countdown, "")

    dash_vm = DashboardViewModel(
        panel_url="http://test",
        api_key="key",
        servers=[vm_matching, vm_differing],
    )
    self.assertTrue(dash_vm.has_servers)
    self.assertEqual(dash_vm.server_count, 2)

    empty_dash_vm = DashboardViewModel(servers=[])
    self.assertFalse(empty_dash_vm.has_servers)
    self.assertEqual(empty_dash_vm.server_count, 0)

  def test_milestone13_response_schemas_validation(self):
    check_now = CheckNowResponse(status="ok", message="Check running")
    self.assertEqual(check_now.status, "ok")
    self.assertEqual(check_now.message, "Check running")

    sim_build = SimulateBuildResponse(status="ok", server_id="srv-1", simulated_build="999", build_id="999")
    self.assertEqual(sim_build.server_id, "srv-1")
    self.assertEqual(sim_build.simulated_build, "999")

    clear_build = ClearBuildResponse(status="ok", server_id="srv-1")
    self.assertEqual(clear_build.server_id, "srv-1")

    sync_name = SyncNameResponse(server_id="srv-1", name="New Name", success=True)
    self.assertEqual(sync_name.name, "New Name")
    self.assertTrue(sync_name.success)

    single_save = SingleServerSaveResponse(status="ok", server_id="srv-1", server={"name": "Saved"})
    self.assertEqual(single_save.server_id, "srv-1")
    self.assertEqual(single_save.server.name, "Saved")

    toggle_test = ToggleTestModeResponse(status="ok", test_mode=True)
    self.assertTrue(toggle_test.test_mode)

    toggle_ssl = ToggleSslVerifyResponse(status="ok", ssl_verify=True)
    self.assertTrue(toggle_ssl.ssl_verify)

    webhook_resp = TestWebhookResponse(status="ok", message="Dispatched", server_id="srv-1")
    self.assertEqual(webhook_resp.server_id, "srv-1")
    self.assertEqual(webhook_resp.message, "Dispatched")

  def test_dashboard_view_model_accepts_notification_preview_without_validation_error(self):
    """Regression test ensuring NotificationPreview instances do not trigger 500 ValidationError."""
    notif = NotificationPreview(
        server_name="Valheim Dedicated",
        message="Update Available: 12345",
        timestamp="12:22 PM",
        embed={"title": "Patch Notes", "description": "Bug fixes"},
    )

    # 1. Direct initialization on DashboardViewModel
    dvm = DashboardViewModel(preview=notif)
    self.assertIsNotNone(dvm.preview)
    self.assertEqual(dvm.preview.server_name, "Valheim Dedicated")

    # 2. from_domain initialization with NotificationPreview
    cfg = AppConfigModel(servers=[ServerModel(server_id="srv-1", name="Valheim")])
    dvm_domain = DashboardViewModel.from_domain(
        config=cfg,
        preview=notif,
    )
    self.assertIsNotNone(dvm_domain.preview)
    self.assertEqual(dvm_domain.preview.server_name, "Valheim Dedicated")
    self.assertEqual(dvm_domain.preview.message, "Update Available: 12345")


if __name__ == "__main__":
  unittest.main()
