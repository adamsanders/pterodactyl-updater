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
      await asyncio.sleep(0.005)  # fire concurrently while save_single_server holds the lock
      await service.toggle_server("srv-1", "auto_restart", True)

    await asyncio.gather(single_save(), toggle_save())

    self.assertEqual(repo.max_concurrent_writers, 1)
    self.assertEqual(repo.cfg.servers[0].name, "Init")
    self.assertTrue(repo.cfg.servers[0].auto_restart)

  async def test_save_single_server_partial_command_preserves_unmodified_fields(self):
    from app.web.schemas import SingleServerSaveRequest
    srv = ServerModel(
        name="Init Name",
        server_id="srv-partial",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
        query_port_offset=1,
    )
    self.repo.load.return_value = AppConfigModel(servers=[srv])

    req = SingleServerSaveRequest(name="Updated Name")
    cmd = req.to_command()
    saved = await self.service.save_single_server("srv-partial", cmd)

    self.assertEqual(saved.name, "Updated Name")
    self.assertEqual(saved.app_id, "896660")
    self.assertEqual(saved.manifest_path, "steamapps/appmanifest_896660.acf")
    self.assertEqual(saved.query_port_offset, 1)

  def test_delete_server_cancels_countdown_and_cleans_simulator_and_runtime_state(self):
    from app.services.build_simulator import BuildSimulatorStore
    mock_countdown_coord = MagicMock()
    sim_store = BuildSimulatorStore()
    sim_store.set_simulated_build("srv-kill", "999999")

    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
        countdown_coordinator=mock_countdown_coord,
        simulator_store=sim_store,
    )

    srv = ServerModel(name="To Delete", server_id="srv-kill")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("srv-kill", current_build="100")

    dto = SettingsUpdateDTO(servers=[srv])
    service.delete_server("srv-kill", dto)

    mock_countdown_coord.cancel_countdown.assert_called_once_with(
        "srv-kill", reason="Server deleted"
    )
    self.assertFalse(sim_store.has_simulated_build("srv-kill"))
    self.assertNotIn("srv-kill", self.runtime_state.get_all_server_states())

  def test_delete_server_by_index_cancels_countdown_and_cleans_stores(self):
    from app.services.build_simulator import BuildSimulatorStore
    mock_countdown_coord = MagicMock()
    sim_store = BuildSimulatorStore()
    sim_store.set_simulated_build("srv-idx", "888888")

    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
        countdown_coordinator=mock_countdown_coord,
        simulator_store=sim_store,
    )

    srv0 = ServerModel(name="First", server_id="srv-0")
    srv1 = ServerModel(name="Second", server_id="srv-idx")
    cfg = AppConfigModel(servers=[srv0, srv1])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("srv-idx")

    dto = SettingsUpdateDTO(servers=[srv0, srv1])
    # Delete by numeric index 1
    service.delete_server(1, dto)

    mock_countdown_coord.cancel_countdown.assert_called_once_with(
        "srv-idx", reason="Server deleted"
    )
    self.assertFalse(sim_store.has_simulated_build("srv-idx"))
    self.assertNotIn("srv-idx", self.runtime_state.get_all_server_states())

  def test_delete_server_with_countdown_manager_fallback(self):
    from app.services.countdown import CountdownManager
    countdown_mgr = CountdownManager()
    countdown_mgr.start("srv-direct", 300)

    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
        countdown=countdown_mgr,
    )

    srv = ServerModel(name="Direct", server_id="srv-direct")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    dto = SettingsUpdateDTO(servers=[srv])
    service.delete_server("srv-direct", dto)

    self.assertFalse(countdown_mgr.is_running("srv-direct"))

  async def test_clean_lock_encapsulation_and_context_manager(self):
    self.assertIsInstance(self.service.lock, asyncio.Lock)

    executed_in_lock = False
    async with self.service.synchronized():
      self.assertTrue(self.service.lock.locked())
      executed_in_lock = True

    self.assertTrue(executed_in_lock)
    self.assertFalse(self.service.lock.locked())

  async def test_execute_locked_under_mutex(self):
    def sync_action(val: int) -> int:
      self.assertTrue(self.service.lock.locked())
      return val * 2

    res = await self.service.execute_locked(sync_action, 21)
    self.assertEqual(res, 42)
    self.assertFalse(self.service.lock.locked())

  def test_no_lockable_operation_class_exists_in_module(self):
    import app.services.server_config_service as mod
    self.assertFalse(
        hasattr(mod, "_LockableOperation"),
        "_LockableOperation helper class must be eliminated from server_config_service",
    )

  async def test_concurrent_add_and_delete_server_serialized_with_lock(self):
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

    initial = [ServerModel(name="Base", server_id="srv-base")]
    repo = ConcurrencyTestRepo(AppConfigModel(servers=initial))
    service = ServerConfigService(
        repository=repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    async def do_add():
      await service.add_server(SettingsUpdateDTO(servers=repo.cfg.servers))

    async def do_delete():
      await service.delete_server("srv-base", SettingsUpdateDTO(servers=repo.cfg.servers))

    await asyncio.gather(do_add(), do_delete())
    self.assertEqual(repo.max_concurrent_writers, 1)

  def test_delete_server_without_settings_command(self):
    from app.services.build_simulator import BuildSimulatorStore
    mock_countdown_coord = MagicMock()
    sim_store = BuildSimulatorStore()
    sim_store.set_simulated_build("srv-no-dto", "111222")

    srv = ServerModel(name="No DTO", server_id="srv-no-dto")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("srv-no-dto")

    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
        countdown_coordinator=mock_countdown_coord,
        simulator_store=sim_store,
    )

    # Calling delete_server with settings=None should succeed cleanly
    service.delete_server("srv-no-dto", None)

    mock_countdown_coord.cancel_countdown.assert_called_once_with(
        "srv-no-dto", reason="Server deleted"
    )
    self.assertFalse(sim_store.has_simulated_build("srv-no-dto"))
    self.assertNotIn("srv-no-dto", self.runtime_state.get_all_server_states())

  def test_delete_server_by_index_with_empty_settings_servers_recovers_id(self):
    from app.services.build_simulator import BuildSimulatorStore
    mock_countdown_coord = MagicMock()
    sim_store = BuildSimulatorStore()
    sim_store.set_simulated_build("srv-target", "333444")

    srv0 = ServerModel(name="Zero", server_id="srv-0")
    srv1 = ServerModel(name="Target", server_id="srv-target")
    cfg = AppConfigModel(servers=[srv0, srv1])
    self.repo.load.return_value = cfg
    self.runtime_state.update_server_state("srv-target")

    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
        countdown_coordinator=mock_countdown_coord,
        simulator_store=sim_store,
    )

    # settings DTO with already empty servers list
    dto = SettingsUpdateDTO(servers=[])
    service.delete_server(1, dto)

    mock_countdown_coord.cancel_countdown.assert_called_once_with(
        "srv-target", reason="Server deleted"
    )
    self.assertFalse(sim_store.has_simulated_build("srv-target"))
    self.assertNotIn("srv-target", self.runtime_state.get_all_server_states())

  def test_delete_server_resolves_runtime_state_from_coordinator_when_missing(self):
    from app.services.runtime_state import RuntimeStateStore
    shared_state = RuntimeStateStore()
    shared_state.update_server_state("srv-coord-only")

    mock_coordinator = MagicMock()
    mock_coordinator.runtime_state = shared_state

    srv = ServerModel(name="Coord Only", server_id="srv-coord-only")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    # ServerConfigService constructed with runtime_state=None
    service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=None,
        countdown_coordinator=mock_coordinator,
    )

    service.delete_server("srv-coord-only")

    self.assertNotIn("srv-coord-only", shared_state.get_all_server_states())

  async def test_save_single_server_awaits_async_save_when_available(self):
    srv = ServerModel(name="Async Test", server_id="srv-async-1")
    cfg = AppConfigModel(servers=[srv])

    class AsyncAwareRepo:
      def __init__(self, c):
        self.c = c
        self.async_save_called = False

      def load(self):
        return self.c.model_copy(deep=True)

      def save(self, config):
        pass

      async def async_save(self, config):
        self.async_save_called = True
        self.c = config.model_copy(deep=True)

    repo = AsyncAwareRepo(cfg)
    service = ServerConfigService(
        repository=repo,
        ptero=self.ptero,
        steam=self.steam,
    )

    req = SingleServerSaveRequest(name="Async Renamed", server_id="srv-async-1")
    await service.save_single_server("srv-async-1", req)

    self.assertTrue(repo.async_save_called)
    self.assertEqual(repo.c.servers[0].name, "Async Renamed")

  async def test_toggle_ssl_verify_persists_state(self):
    cfg = AppConfigModel(ssl_verify=False)
    self.repo.load.return_value = cfg

    res = await self.service.toggle_ssl_verify(True)
    self.assertTrue(res)
    self.repo.save.assert_called_once()
    self.assertTrue(cfg.ssl_verify)

  async def test_toggle_test_mode_persists_state(self):
    cfg = AppConfigModel(test_mode=False)
    self.repo.load.return_value = cfg

    res = await self.service.toggle_test_mode(True)
    self.assertTrue(res)
    self.repo.save.assert_called_once()
    self.assertTrue(cfg.test_mode)

  async def test_update_server_toggle_persists_field(self):
    srv = ServerModel(name="Test Box", server_id="srv-toggle", auto_restart=False)
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    updated = await self.service.update_server_toggle("srv-toggle", "auto_restart", True)
    self.assertTrue(updated.auto_restart)
    self.repo.save.assert_called_once()
    self.assertTrue(srv.auto_restart)

  async def test_update_server_toggle_invalid_field_raises(self):
    srv = ServerModel(name="Test Box", server_id="srv-toggle")
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    with self.assertRaises(ConfigurationError):
      await self.service.update_server_toggle("srv-toggle", "invalid_field", True)

