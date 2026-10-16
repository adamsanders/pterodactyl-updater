import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.models import AppConfigModel, ServerModel, SettingsUpdateDTO
from app.services.server_service import ServerService
from app.services.build_simulator import BuildSimulatorStore
from app.services.preview_store import WebhookPreviewStore
from app.services.countdown import CountdownManager
from app.web.schemas import SettingsFormData
from starlette.datastructures import FormData


class TestServerServiceCleanArchitecture(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.ptero.invalidate_power_cache = MagicMock()
    self.steam = AsyncMock()

    self.discord = AsyncMock()
    self.preview_store = WebhookPreviewStore()
    self.simulator_store = BuildSimulatorStore()
    self.countdown = CountdownManager()

    self.service = ServerService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        discord=self.discord,
        preview_store=self.preview_store,
        simulator_store=self.simulator_store,
        countdown=self.countdown,
    )

  def test_service_module_does_not_import_web_layer(self):
    import app.services.server_service as mod
    # Inspect all module attributes and imported modules
    for name, val in vars(mod).items():
      if hasattr(val, "__module__") and val.__module__:
        self.assertFalse(
            val.__module__.startswith("app.web"),
            f"Layer leak detected: {name} ({val}) is imported from app.web into app.services.server_service",
        )

  def test_save_settings_with_dto(self):
    cfg = AppConfigModel(panel_url="http://old.com", api_key="old")
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(
        panel_url="http://new.com",
        api_key="new_key",
        check_interval=5,
        discord_webhook="http://webhook",
        test_mode=True,
        servers=[ServerModel(name="Srv1", server_id="id1")],
    )

    self.service.save_settings(dto)

    self.repo.save.assert_called_once()
    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(saved_cfg.panel_url, "http://new.com")
    self.assertEqual(saved_cfg.api_key, "new_key")
    self.assertEqual(saved_cfg.check_interval, 5)
    self.assertEqual(len(saved_cfg.servers), 1)

  def test_add_server_with_dto(self):
    cfg = AppConfigModel(servers=[ServerModel(name="Existing", server_id="id1")])
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(
        panel_url="http://new.com",
        api_key="key",
        servers=[ServerModel(name="Existing", server_id="id1")],
    )

    self.service.add_server(dto)

    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(len(saved_cfg.servers), 2)
    self.assertEqual(saved_cfg.servers[0].name, "Existing")
    self.assertEqual(saved_cfg.servers[1].name, "New Server")

  def test_delete_server_with_dto(self):
    cfg = AppConfigModel(
        servers=[
            ServerModel(name="S1", server_id="id1"),
            ServerModel(name="S2", server_id="id2"),
        ]
    )
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(
        servers=[
            ServerModel(name="S1", server_id="id1"),
            ServerModel(name="S2", server_id="id2"),
        ]
    )

    self.service.delete_server(0, dto)

    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(len(saved_cfg.servers), 1)
    self.assertEqual(saved_cfg.servers[0].name, "S2")

  async def test_rename_server_with_dto(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[ServerModel(name="Old Name", server_id="id1")],
    )
    self.repo.load.return_value = cfg
    self.ptero.rename_server.return_value = (True, None)

    dto = SettingsUpdateDTO(
        panel_url="http://panel.test",
        api_key="key",
        servers=[ServerModel(name="Old Name", server_id="id1")],
    )

    success = await self.service.rename_server(0, "New Name", dto)
    self.assertTrue(success)

    self.ptero.rename_server.assert_called_once_with(
        "http://panel.test", "key", "id1", "New Name"
    )
    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(saved_cfg.servers[0].name, "New Name")
    self.assertEqual(saved_cfg.servers[0].last_status, "Renamed in Pterodactyl")

  async def test_form_data_parser_creates_settings_dto(self):
    form = FormData({
        "panel_url": "http://form.test",
        "api_key": "ptlc_secret",
        "check_interval": "10",
        "discord_webhook": "https://discord.gg/hook",
        "test_mode": "true",
        "srv_id_0": "srv123",
        "srv_appid_0": "896660",
        "srv_manifest_0": "steamapps/appmanifest_896660.acf",
        "srv_autorestart_0": "true",
        "srv_discord_0": "true",
        "srv_warningame_0": "true",
        "srv_warndiscord_0": "false",
    })

    current_servers = [ServerModel(name="Valheim 1", server_id="initial_id")]
    dto = await SettingsFormData.from_form(form, current_servers)

    self.assertIsInstance(dto, SettingsUpdateDTO)
    self.assertEqual(dto.panel_url, "http://form.test")
    self.assertEqual(dto.api_key, "ptlc_secret")
    self.assertEqual(dto.check_interval, 10)
    self.assertTrue(dto.test_mode)
    self.assertEqual(len(dto.servers), 1)
    self.assertEqual(dto.servers[0].name, "Valheim 1")
    self.assertEqual(dto.servers[0].server_id, "srv123")
    self.assertTrue(dto.servers[0].auto_restart)

  async def test_form_data_parser_with_server_id_keys(self):
    form = FormData({
        "panel_url": "http://form.test",
        "api_key": "ptlc_secret",
        "check_interval": "10",
        "discord_webhook": "https://discord.gg/hook",
        "test_mode": "true",
        "srv_id_alpha-uuid": "alpha-uuid",
        "srv_appid_alpha-uuid": "2394010",
        "srv_manifest_alpha-uuid": "steamapps/appmanifest_2394010.acf",
        "srv_autorestart_alpha-uuid": "true",
        "srv_discord_alpha-uuid": "false",
        "srv_warningame_alpha-uuid": "true",
        "srv_warndiscord_alpha-uuid": "true",
    })

    current_servers = [ServerModel(name="Palworld", server_id="alpha-uuid")]
    dto = await SettingsFormData.from_form(form, current_servers)

    self.assertEqual(len(dto.servers), 1)
    self.assertEqual(dto.servers[0].server_id, "alpha-uuid")
    self.assertEqual(dto.servers[0].app_id, "2394010")
    self.assertTrue(dto.servers[0].auto_restart)
    self.assertFalse(dto.servers[0].discord_alerts)
    self.assertTrue(dto.servers[0].warn_ingame_countdown)
    self.assertTrue(dto.servers[0].warn_discord_countdown)

  def test_find_server_index_by_server_id_and_legacy_index(self):
    servers = [
        ServerModel(name="Server A", server_id="uuid-aaa"),
        ServerModel(name="Server B", server_id="uuid-bbb"),
        ServerModel(name="Server C", server_id="uuid-ccc"),
    ]

    # Exact server_id matches
    self.assertEqual(self.service.find_server_index(servers, "uuid-aaa"), 0)
    self.assertEqual(self.service.find_server_index(servers, "uuid-bbb"), 1)
    self.assertEqual(self.service.find_server_index(servers, "uuid-ccc"), 2)

    # Legacy numeric index fallback
    self.assertEqual(self.service.find_server_index(servers, 0), 0)
    self.assertEqual(self.service.find_server_index(servers, "1"), 1)
    self.assertEqual(self.service.find_server_index(servers, 2), 2)

    # Nonexistent identifier
    self.assertIsNone(self.service.find_server_index(servers, "uuid-unknown"))
    self.assertIsNone(self.service.find_server_index(servers, 99))
    self.assertIsNone(self.service.find_server_index(servers, -1))
    self.assertIsNone(self.service.find_server_index(servers, ""))

  def test_delete_server_by_server_id_reordered_or_non_contiguous(self):
    cfg = AppConfigModel(
        servers=[
            ServerModel(name="Alpha", server_id="id-alpha"),
            ServerModel(name="Beta", server_id="id-beta"),
            ServerModel(name="Gamma", server_id="id-gamma"),
        ]
    )
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(
        servers=[
            ServerModel(name="Alpha", server_id="id-alpha"),
            ServerModel(name="Beta", server_id="id-beta"),
            ServerModel(name="Gamma", server_id="id-gamma"),
        ]
    )

    # Delete middle server by server_id instead of index
    self.service.delete_server("id-beta", dto)

    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(len(saved_cfg.servers), 2)
    self.assertEqual([s.server_id for s in saved_cfg.servers], ["id-alpha", "id-gamma"])

  async def test_rename_server_by_server_id(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[
            ServerModel(name="First", server_id="id-first"),
            ServerModel(name="Target Server", server_id="id-target"),
        ],
    )
    self.repo.load.return_value = cfg
    self.ptero.rename_server.return_value = (True, None)

    dto = SettingsUpdateDTO(
        panel_url="http://panel.test",
        api_key="key",
        servers=[
            ServerModel(name="First", server_id="id-first"),
            ServerModel(name="Target Server", server_id="id-target"),
        ],
    )

    success = await self.service.rename_server("id-target", "Renamed Target", dto)
    self.assertTrue(success)
    self.ptero.rename_server.assert_called_once_with(
        "http://panel.test", "key", "id-target", "Renamed Target"
    )

    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(saved_cfg.servers[1].name, "Renamed Target")
    self.assertEqual(saved_cfg.servers[1].last_status, "Renamed in Pterodactyl")

  async def test_send_power_action_by_server_id(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[
            ServerModel(name="First", server_id="id-first"),
            ServerModel(name="Second", server_id="id-second"),
        ],
    )
    self.repo.load.return_value = cfg
    self.ptero.send_power_signal.return_value = (True, None)

    success, err = await self.service.send_power_action("id-second", "restart")
    self.assertTrue(success)
    self.assertIsNone(err)
    self.ptero.send_power_signal.assert_called_once_with(
        panel_url="http://panel.test",
        api_key="key",
        server_id="id-second",
        signal="restart",
    )

  def test_simulate_build_update_by_server_id(self):
    cfg = AppConfigModel(
        test_mode=True,
        servers=[
            ServerModel(name="First", server_id="id-first"),
            ServerModel(name="Second", server_id="id-second"),
        ],
    )
    self.repo.load.return_value = cfg

    success, err, target_id = self.service.simulate_build_update("id-second", "999888")
    self.assertTrue(success)
    self.assertIsNone(err)
    self.assertEqual(target_id, "id-second")
    self.assertEqual(self.simulator_store.get_simulated_build("id-second"), "999888")

  async def test_toggle_test_mode_orchestrates_clearing_and_inspection(self):
    orchestrator = MagicMock()
    orchestrator.run_update_check = AsyncMock()
    self.service.orchestrator = orchestrator

    cfg = AppConfigModel(test_mode=True)
    self.repo.load.return_value = cfg

    # Toggle OFF -> should clear restarted builds and trigger update check
    await self.service.toggle_test_mode(False)
    orchestrator.clear_restarted_build.assert_called_once()
    orchestrator.run_update_check.assert_called_once()

  async def test_trigger_simulated_build_orchestrates_simulation_and_check(self):
    orchestrator = MagicMock()
    orchestrator.run_update_check = AsyncMock()
    self.service.orchestrator = orchestrator

    cfg = AppConfigModel(test_mode=True, servers=[ServerModel(name="Srv1", server_id="srv-1")])
    self.repo.load.return_value = cfg

    target_id = await self.service.trigger_simulated_build("srv-1", "999888")
    self.assertEqual(target_id, "srv-1")
    orchestrator.clear_restarted_build.assert_called_once_with("srv-1")
    orchestrator.run_update_check.assert_called_once_with(target_server_id="srv-1")

  async def test_trigger_immediate_check(self):
    orchestrator = MagicMock()
    orchestrator.run_update_check = AsyncMock()
    self.service.orchestrator = orchestrator

    await self.service.trigger_immediate_check()
    self.ptero.invalidate_power_cache.assert_called_once()
    orchestrator.run_update_check.assert_called_once()

  def test_routes_module_does_not_depend_on_orchestrator(self):
    import app.web.routes as routes_mod
    self.assertNotIn("UpdateOrchestrator", vars(routes_mod))

  async def test_lookup_server_name_success(self):
    from app.core.models import ServerNameResult
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="test-key")
    self.repo.load.return_value = cfg
    self.ptero.get_server_name.return_value = ServerNameResult("Satisfactory Server", None)

    name = await self.service.lookup_server_name("srv-sat")
    self.assertEqual(name, "Satisfactory Server")
    self.ptero.get_server_name.assert_called_once_with(
        "http://panel.test", "test-key", "srv-sat", raise_on_error=True
    )

  async def test_lookup_server_name_empty_server_id_raises_configuration_error(self):
    from app.core.exceptions import ConfigurationError
    with self.assertRaises(ConfigurationError):
      await self.service.lookup_server_name("   ")

  async def test_lookup_server_name_unconfigured_panel_raises_configuration_error(self):
    from app.core.exceptions import ConfigurationError
    self.repo.load.return_value = AppConfigModel(panel_url="", api_key="")
    with self.assertRaises(ConfigurationError):
      await self.service.lookup_server_name("srv-1")

  async def test_sync_server_name_persists_to_repository(self):
    from app.core.models import ServerNameResult
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="test-key",
        servers=[ServerModel(name="New Server", server_id="srv-rust")],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_server_name.return_value = ServerNameResult("Rust Official", None)

    synced_name = await self.service.sync_server_name("srv-rust")
    self.assertEqual(synced_name, "Rust Official")
    self.repo.save.assert_called_once()
    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(saved_cfg.servers[0].name, "Rust Official")

  async def test_sync_server_name_with_id_override(self):
    from app.core.models import ServerNameResult
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="test-key",
        servers=[ServerModel(name="New Server", server_id="")],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_server_name.return_value = ServerNameResult("Enshrouded World", None)

    synced_name = await self.service.sync_server_name(0, server_id_override="srv-enshrouded")
    self.assertEqual(synced_name, "Enshrouded World")
    saved_cfg = self.repo.save.call_args[0][0]
    self.assertEqual(saved_cfg.servers[0].name, "Enshrouded World")
    self.assertEqual(saved_cfg.servers[0].server_id, "srv-enshrouded")

  async def test_sync_server_name_not_found_raises(self):
    from app.core.exceptions import ServerNotFoundError
    self.repo.load.return_value = AppConfigModel(panel_url="http://p", api_key="k", servers=[])
    with self.assertRaises(ServerNotFoundError):
      await self.service.sync_server_name("nonexistent")

  def test_update_server_toggle_persists(self):
    cfg = AppConfigModel(
        servers=[ServerModel(name="Srv1", server_id="srv-1", auto_restart=False)]
    )
    self.repo.load.return_value = cfg
    self.service.update_server_toggle("srv-1", "auto_restart", True)
    self.repo.save.assert_called_once()
    saved = self.repo.save.call_args[0][0]
    self.assertTrue(saved.servers[0].auto_restart)

  def test_update_server_toggle_invalid_field_raises(self):
    from app.core.exceptions import ConfigurationError
    cfg = AppConfigModel(servers=[ServerModel(name="Srv1", server_id="srv-1")])
    self.repo.load.return_value = cfg
    with self.assertRaises(ConfigurationError):
      self.service.update_server_toggle("srv-1", "invalid_field", True)

  async def test_save_single_server_persists_text_fields(self):
    cfg = AppConfigModel(
        servers=[ServerModel(name="Old Name", server_id="srv-1", app_id="111", manifest_path="old.acf")]
    )
    self.repo.load.return_value = cfg
    updated = await self.service.save_single_server("srv-1", {
        "name": "Updated Name",
        "server_id": "srv-1-new",
        "app_id": "222",
        "manifest_path": "new.acf",
    })
    self.repo.save.assert_called_once()
    self.assertEqual(updated.name, "Updated Name")
    self.assertEqual(updated.server_id, "srv-1-new")
    self.assertEqual(updated.app_id, "222")
    self.assertEqual(updated.manifest_path, "new.acf")

  async def test_save_single_server_auto_syncs_new_server_name(self):
    from app.core.models import ServerNameResult
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[ServerModel(name="New Server", server_id="")]
    )
    self.repo.load.return_value = cfg
    self.ptero.get_server_name.return_value = ServerNameResult("Ptero Detected Name", None)

    updated = await self.service.save_single_server(0, {
        "name": "New Server",
        "server_id": "srv-new-hash",
        "app_id": "896660",
        "manifest_path": "steamapps/appmanifest_896660.acf",
    })
    self.assertEqual(updated.name, "Ptero Detected Name")

  async def test_detect_server_details_delegates_to_pterodactyl_gateway(self):
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="test-key")
    self.repo.load.return_value = cfg
    self.ptero.detect_server_details.return_value = {
        "name": "Enshrouded Server",
        "app_id": "2230650",
        "manifest_path": "steamapps/appmanifest_2230650.acf",
    }

    details = await self.service.detect_server_details("srv-enshrouded")
    self.assertEqual(details["name"], "Enshrouded Server")
    self.assertEqual(details["app_id"], "2230650")
    self.ptero.detect_server_details.assert_called_once_with(
        "http://panel.test", "test-key", "srv-enshrouded"
    )

  async def test_detect_server_details_unconfigured_panel_raises(self):
    from app.core.exceptions import ConfigurationError
    self.repo.load.return_value = AppConfigModel(panel_url="", api_key="")
    with self.assertRaises(ConfigurationError):
      await self.service.detect_server_details("srv-1")

  async def test_search_steam_games_delegates_to_steam_gateway(self):
    self.steam.search_games.return_value = [
        {"app_id": "2230650", "name": "Enshrouded Dedicated Server", "type": "dedicated_server"}
    ]
    results = await self.service.search_steam_games("enshrouded")
    self.assertEqual(len(results), 1)
    self.assertEqual(results[0]["app_id"], "2230650")
    self.steam.search_games.assert_called_once_with("enshrouded")


class TestServerIdRouteIntegration(unittest.TestCase):

  def setUp(self):
    from fastapi.testclient import TestClient
    from app.main import app

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
    from app.core.models import OperationResult

    self.app.state.server_service.find_server_index.return_value = 1
    self.app.state.server_service.send_power_action = AsyncMock(
        return_value=OperationResult(False, "Invalid power action 'kaboom'.")
    )
    res = self.client.post("/api/servers/srv-beta/power/kaboom")
    self.assertEqual(res.status_code, 400)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "InvalidPowerActionError")
    self.assertIn("Invalid power action 'kaboom'", data.get("message", ""))

  def test_power_action_route_failure_bubbles_pterodactyl_error(self):
    from app.core.models import OperationResult

    self.app.state.server_service.send_power_action = AsyncMock(
        return_value=OperationResult(False, "Panel HTTP 500: Node offline")
    )
    res = self.client.post("/api/servers/srv-beta/power/restart")
    self.assertEqual(res.status_code, 500)
    data = res.json()
    self.assertEqual(data.get("status"), "error")
    self.assertEqual(data.get("error"), "PterodactylApiError")
    self.assertIn("Panel HTTP 500", data.get("message", ""))

  def test_simulate_build_failure_bubbles_simulation_error(self):
    from app.core.exceptions import SimulationError

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
    from fastapi.testclient import TestClient
    from app.main import app
    from app.web.dependencies import get_service

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
    self.assertEqual(res.json(), {"status": "ok", "name": "Synced Server Name"})
    self.mock_service.sync_server_name.assert_called_once_with("srv-beta", server_id_override="srv-beta")

  def test_toggle_server_setting_route(self):
    self.mock_service.update_server_toggle = MagicMock()
    res = self.client.post("/api/servers/srv-beta/toggle", json={"field": "auto_restart", "value": True})
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "field": "auto_restart", "value": True})
    self.mock_service.update_server_toggle.assert_called_once_with("srv-beta", "auto_restart", True)

  def test_save_single_server_route(self):
    saved_model = ServerModel(name="Saved Server", server_id="srv-beta", app_id="123", manifest_path="test.acf")
    self.mock_service.save_single_server = AsyncMock(return_value=saved_model)
    res = self.client.post(
        "/api/servers/srv-beta/save",
        json={"name": "Saved Server", "server_id": "srv-beta", "app_id": "123", "manifest_path": "test.acf"}
    )
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json().get("status"), "ok")
    self.assertEqual(res.json().get("server", {}).get("name"), "Saved Server")

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


if __name__ == "__main__":
  unittest.main()


