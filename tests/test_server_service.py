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


if __name__ == "__main__":
  unittest.main()
