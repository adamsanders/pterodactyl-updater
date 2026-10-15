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
    self.app.state.server_service.simulate_build_update.return_value = (True, None, "srv-beta")
    self.app.state.orchestrator.run_update_check = AsyncMock()

    res = self.client.post(
        "/api/test/simulate-build",
        json={"server_id": "srv-beta", "build_id": "777777"},
    )
    self.assertEqual(res.status_code, 200)
    self.app.state.server_service.simulate_build_update.assert_called_once_with("srv-beta", "777777")


if __name__ == "__main__":
  unittest.main()
