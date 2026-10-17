import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ConfigurationError, ServerNotFoundError
from app.core.models import (
    AppConfigModel,
    ServerModel,
    ServerNameResult,
)
from app.web.schemas import (
    SettingsUpdateDTO,
    SingleServerSaveRequest,
)
from app.services.runtime_state import RuntimeStateStore
from app.services.server_config_service import ServerConfigService


class TestServerConfigService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.runtime_state = RuntimeStateStore()

    self.service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

  def test_find_server_index(self):
    servers = [
        ServerModel(name="Server A", server_id="srv-a"),
        ServerModel(name="Server B", server_id="srv-b"),
    ]
    self.assertEqual(self.service.find_server_index(servers, "srv-b"), 1)
    self.assertEqual(self.service.find_server_index(servers, "SRV-A"), 0)
    self.assertEqual(self.service.find_server_index(servers, 1), 1)
    self.assertIsNone(self.service.find_server_index(servers, "srv-c"))
    self.assertIsNone(self.service.find_server_index(servers, 99))
    self.assertIsNone(self.service.find_server_index(servers, ""))

  def test_save_settings_and_seed_runtime_state(self):
    cfg = AppConfigModel(servers=[ServerModel(server_id="old-id")])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("old-id", current_build="100")

    dto = SettingsUpdateDTO(
        panel_url="http://panel.test",
        api_key="key",
        servers=[ServerModel(server_id="new-id", name="New Srv")],
    )
    self.service.save_settings(dto)

    self.repo.save.assert_called_once()
    all_states = self.runtime_state.get_all_server_states()
    self.assertNotIn("old-id", all_states)
    self.assertIn("new-id", all_states)

  def test_add_server(self):
    cfg = AppConfigModel(servers=[])
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(
        panel_url="http://panel.test",
        api_key="key",
        servers=[],
    )
    self.service.add_server(dto)

    self.repo.save.assert_called_once()
    saved = self.repo.save.call_args[0][0]
    self.assertEqual(len(saved.servers), 1)
    self.assertEqual(saved.servers[0].name, "New Server")

  def test_delete_server(self):
    srv1 = ServerModel(name="A", server_id="srv-a")
    srv2 = ServerModel(name="B", server_id="srv-b")
    cfg = AppConfigModel(servers=[srv1, srv2])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("srv-a")
    self.runtime_state.update_server_state("srv-b")

    dto = SettingsUpdateDTO(servers=[srv1, srv2])
    self.service.delete_server("srv-a", dto)

    self.repo.save.assert_called_once()
    saved = self.repo.save.call_args[0][0]
    self.assertEqual(len(saved.servers), 1)
    self.assertEqual(saved.servers[0].server_id, "srv-b")
    self.assertNotIn("srv-a", self.runtime_state.get_all_server_states())

  async def test_save_single_server_with_typed_request(self):
    srv = ServerModel(name="Old Name", server_id="srv-1", app_id="111")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    req = SingleServerSaveRequest(
        name="Updated Name",
        server_id="srv-2",
        app_id="222",
        manifest_path="manifest.acf",
        query_port_offset=5,
        broadcast_command_template="broadcast {message}",
    )

    updated = await self.service.save_single_server("srv-1", req)

    self.repo.save.assert_called_once()
    self.assertEqual(updated.name, "Updated Name")
    self.assertEqual(updated.server_id, "srv-2")
    self.assertEqual(updated.app_id, "222")
    self.assertEqual(updated.manifest_path, "manifest.acf")
    self.assertEqual(updated.query_port_offset, 5)
    self.assertEqual(updated.broadcast_command_template, "broadcast {message}")

  async def test_save_single_server_with_dict(self):
    srv = ServerModel(name="Old Name", server_id="srv-1")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    data = {
        "name": "Dict Name",
        "server_id": "srv-1",
        "app_id": "333",
        "query_port_offset": "10",
        "broadcast_command_template": "servermsg {message}",
    }

    updated = await self.service.save_single_server("srv-1", data)

    self.assertEqual(updated.name, "Dict Name")
    self.assertEqual(updated.app_id, "333")
    self.assertEqual(updated.query_port_offset, 10)
    self.assertEqual(updated.broadcast_command_template, "servermsg {message}")

  def test_update_server_toggle_validation(self):
    srv = ServerModel(name="Valheim", server_id="srv-1", auto_restart=False)
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    self.service.update_server_toggle("srv-1", "auto_restart", True)
    self.assertTrue(srv.auto_restart)

    with self.assertRaises(ConfigurationError):
      self.service.update_server_toggle("srv-1", "invalid_field", True)

    with self.assertRaises(ServerNotFoundError):
      self.service.update_server_toggle("non_existent", "auto_restart", True)

  async def test_toggle_server_method(self):
    srv = ServerModel(
        name="Valheim",
        server_id="srv-1",
        auto_restart=False,
        auto_update=True,
    )
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    res = await self.service.toggle_server("srv-1", "auto_restart", True)
    self.assertTrue(res.auto_restart)
    self.assertTrue(srv.auto_restart)

    res2 = await self.service.toggle_server("srv-1", "discord_alerts", False)
    self.assertFalse(res2.discord_alerts)
    self.assertFalse(srv.discord_alerts)

    with self.assertRaises(ConfigurationError):
      await self.service.toggle_server("srv-1", "invalid_field", True)

    with self.assertRaises(ServerNotFoundError):
      await self.service.toggle_server("non_existent", "auto_restart", True)

  async def test_concurrent_read_modify_write_serialized_with_lock(self):
    class ConcurrencyTestRepo:
      def __init__(self, initial_cfg: AppConfigModel):
        self.cfg = initial_cfg.model_copy(deep=True)
        self.active_writers = 0
        self.max_concurrent_writers = 0

      def load(self) -> AppConfigModel:
        return self.cfg.model_copy(deep=True)

      def save(self, config: AppConfigModel) -> None:
        self.active_writers += 1
        if self.active_writers > self.max_concurrent_writers:
          self.max_concurrent_writers = self.active_writers
        time.sleep(0.005)
        self.cfg = config.model_copy(deep=True)
        self.active_writers -= 1

    initial_servers = [
        ServerModel(name=f"Server {i}", server_id=f"srv-{i}", auto_restart=False)
        for i in range(5)
    ]
    repo = ConcurrencyTestRepo(AppConfigModel(servers=initial_servers))
    service = ServerConfigService(
        repository=repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    async def toggle_one(idx: int):
      await service.toggle_server(f"srv-{idx}", "auto_restart", True)

    tasks = [toggle_one(i) for i in range(5)]
    await asyncio.gather(*tasks)

    # Concurrency verification:
    # 1. Mutex prevented simultaneous writes (max_concurrent_writers == 1)
    self.assertEqual(repo.max_concurrent_writers, 1)
    # 2. No lost updates: all 5 servers were updated to True
    self.assertEqual(len(repo.cfg.servers), 5)
    for s in repo.cfg.servers:
      self.assertTrue(s.auto_restart)

  async def test_concurrent_save_settings_serialized_with_lock(self):
    class ConcurrencyTestRepo:
      def __init__(self, initial_cfg: AppConfigModel):
        self.cfg = initial_cfg.model_copy(deep=True)
        self.active_writers = 0
        self.max_concurrent_writers = 0

      def load(self) -> AppConfigModel:
        return self.cfg.model_copy(deep=True)

      def save(self, config: AppConfigModel) -> None:
        self.active_writers += 1
        if self.active_writers > self.max_concurrent_writers:
          self.max_concurrent_writers = self.active_writers
        time.sleep(0.005)
        self.cfg = config.model_copy(deep=True)
        self.active_writers -= 1

    repo = ConcurrencyTestRepo(AppConfigModel(servers=[]))
    service = ServerConfigService(
        repository=repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    async def save_one(val: int):
      await service.save_settings(SettingsUpdateDTO(check_interval=val + 1, servers=[]))

    tasks = [save_one(i) for i in range(5)]
    await asyncio.gather(*tasks)

    self.assertEqual(repo.max_concurrent_writers, 1)

  async def test_concurrent_update_server_toggle_serialized_with_lock(self):
    class ConcurrencyTestRepo:
      def __init__(self, initial_cfg: AppConfigModel):
        self.cfg = initial_cfg.model_copy(deep=True)
        self.active_writers = 0
        self.max_concurrent_writers = 0

      def load(self) -> AppConfigModel:
        return self.cfg.model_copy(deep=True)

      def save(self, config: AppConfigModel) -> None:
        self.active_writers += 1
        if self.active_writers > self.max_concurrent_writers:
          self.max_concurrent_writers = self.active_writers
        time.sleep(0.005)
        self.cfg = config.model_copy(deep=True)
        self.active_writers -= 1

    initial_servers = [
        ServerModel(name=f"Server {i}", server_id=f"srv-{i}", auto_restart=False)
        for i in range(5)
    ]
    repo = ConcurrencyTestRepo(AppConfigModel(servers=initial_servers))
    service = ServerConfigService(
        repository=repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    async def toggle_one(idx: int):
      await service.update_server_toggle(f"srv-{idx}", "auto_restart", True)

    tasks = [toggle_one(i) for i in range(5)]
    await asyncio.gather(*tasks)

    self.assertEqual(repo.max_concurrent_writers, 1)
    for s in repo.cfg.servers:
      self.assertTrue(s.auto_restart)

  async def test_concurrent_interleaved_save_single_server_and_toggle_server(self):
    class ConcurrencyTestRepo:
      def __init__(self, initial_cfg: AppConfigModel):
        self.cfg = initial_cfg.model_copy(deep=True)
        self.active_writers = 0
        self.max_concurrent_writers = 0

      def load(self) -> AppConfigModel:
        return self.cfg.model_copy(deep=True)

      def save(self, config: AppConfigModel) -> None:
        self.active_writers += 1
        if self.active_writers > self.max_concurrent_writers:
          self.max_concurrent_writers = self.active_writers
        time.sleep(0.005)
        self.cfg = config.model_copy(deep=True)
        self.active_writers -= 1

    ptero = AsyncMock()
    async def delayed_get_server_name(*args, **kwargs):
      await asyncio.sleep(0.02)
      return ServerNameResult("Synced Remote Name", None)
    ptero.get_server_name = delayed_get_server_name

    initial_servers = [ServerModel(name="Init", server_id="srv-1", auto_restart=False)]
    repo = ConcurrencyTestRepo(AppConfigModel(panel_url="http://panel.test", api_key="k", servers=initial_servers))
    service = ServerConfigService(
        repository=repo,
        ptero=ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    async def single_save():
      await service.save_single_server("srv-1", {"name": ""})

    async def toggle_save():
      await asyncio.sleep(0.005)  # fire while save_single_server is awaiting Pterodactyl get_server_name
      await service.toggle_server("srv-1", "auto_restart", True)

    await asyncio.gather(single_save(), toggle_save())

    self.assertEqual(repo.max_concurrent_writers, 1)
    self.assertEqual(repo.cfg.servers[0].name, "Synced Remote Name")
    self.assertTrue(repo.cfg.servers[0].auto_restart)
