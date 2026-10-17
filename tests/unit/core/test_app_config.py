import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    PterodactylApiError,
    ServerNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.models import (
    AppConfigModel,
    LocalBuildResult,
    OperationResult,
    ServerModel,
    ServerNameResult,
    ServerUpdateStatus,
)
from app.services.runtime_state import RuntimeStateStore
from app.services.server_config_service import ServerConfigService
from app.services.server_power_service import ServerPowerService
from app.services.server_service import ServerService
from app.web.schemas import SettingsUpdateDTO, SingleServerSaveRequest


class TestAppConfigModelFindServerIndex(unittest.TestCase):
  """Dedicated unit tests for AppConfigModel.find_server_index."""

  def setUp(self):
    self.servers = [
        ServerModel(server_id="srv-alpha", name="Alpha Server"),
        ServerModel(server_id="srv-beta", name="Beta Server"),
        ServerModel(server_id="srv-gamma", name="Gamma Server"),
    ]
    self.cfg = AppConfigModel(servers=self.servers)

  def test_find_by_exact_server_id(self):
    self.assertEqual(self.cfg.find_server_index("srv-alpha"), 0)
    self.assertEqual(self.cfg.find_server_index("srv-beta"), 1)
    self.assertEqual(self.cfg.find_server_index("srv-gamma"), 2)

  def test_find_by_case_insensitive_server_id(self):
    self.assertEqual(self.cfg.find_server_index("SRV-ALPHA"), 0)
    self.assertEqual(self.cfg.find_server_index("Srv-Beta"), 1)

  def test_find_by_whitespace_padded_server_id(self):
    self.assertEqual(self.cfg.find_server_index("  srv-beta  "), 1)

  def test_find_by_numeric_integer_index(self):
    self.assertEqual(self.cfg.find_server_index(0), 0)
    self.assertEqual(self.cfg.find_server_index(1), 1)
    self.assertEqual(self.cfg.find_server_index(2), 2)

  def test_find_by_numeric_string_index(self):
    self.assertEqual(self.cfg.find_server_index("0"), 0)
    self.assertEqual(self.cfg.find_server_index("1"), 1)
    self.assertEqual(self.cfg.find_server_index("2"), 2)

  def test_find_out_of_bounds_numeric_index(self):
    self.assertIsNone(self.cfg.find_server_index(3))
    self.assertIsNone(self.cfg.find_server_index(99))
    self.assertIsNone(self.cfg.find_server_index("99"))

  def test_find_negative_numeric_index(self):
    self.assertIsNone(self.cfg.find_server_index(-1))
    self.assertIsNone(self.cfg.find_server_index("-1"))

  def test_find_empty_or_whitespace_identifier(self):
    self.assertIsNone(self.cfg.find_server_index(""))
    self.assertIsNone(self.cfg.find_server_index("   "))

  def test_find_unknown_server_id(self):
    self.assertIsNone(self.cfg.find_server_index("srv-unknown"))

  def test_find_with_server_having_empty_server_id(self):
    cfg_empty = AppConfigModel(servers=[
        ServerModel(server_id="", name="Empty ID Server"),
        ServerModel(server_id="srv-valid", name="Valid Server"),
    ])
    self.assertEqual(cfg_empty.find_server_index("srv-valid"), 1)
    self.assertIsNone(cfg_empty.find_server_index(""))

  def test_find_on_empty_config(self):
    empty_cfg = AppConfigModel(servers=[])
    self.assertIsNone(empty_cfg.find_server_index("srv-1"))
    self.assertIsNone(empty_cfg.find_server_index(0))

  def test_find_with_none_identifier(self):
    self.assertIsNone(self.cfg.find_server_index(None))

  def test_find_with_boolean_identifiers(self):
    self.assertIsNone(self.cfg.find_server_index(False))
    self.assertIsNone(self.cfg.find_server_index(True))

  def test_server_id_precedence_over_numeric_index(self):
    cfg_special = AppConfigModel(servers=[
        ServerModel(server_id="srv-zero", name="Zero Server"),
        ServerModel(server_id="0", name="Server with ID 0"),
    ])
    self.assertEqual(cfg_special.find_server_index("0"), 1)


class TestDomainPurity(unittest.TestCase):
  """Verifies ServerModel has no mutable private attributes and emits DeprecationWarning."""

  def test_server_model_has_no_private_attrs(self):
    private_attrs = getattr(ServerModel, "__private_attributes__", {})
    self.assertNotIn("_current_build", private_attrs)
    self.assertNotIn("_latest_build", private_attrs)
    self.assertNotIn("_last_status", private_attrs)

  def test_server_model_deprecation_property_access(self):
    srv = ServerModel(
        server_id="test-srv",
        name="Test Server",
        app_id="12345",
        manifest_path="manifest.acf",
        current_build="100",
        latest_build="200",
    )

    with warnings.catch_warnings(record=True) as recorded_warnings:
      warnings.simplefilter("always")
      c_build = srv.current_build
      l_build = srv.latest_build
      status = srv.last_status

      self.assertEqual(c_build, "100")
      self.assertEqual(l_build, "200")
      self.assertEqual(status, ServerUpdateStatus.IDLE)

      prop_warnings = [
          w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
      ]
      self.assertGreaterEqual(len(prop_warnings), 3)

  def test_server_model_deprecation_property_mutation(self):
    srv = ServerModel(
        server_id="test-srv",
        name="Test Server",
        app_id="12345",
        manifest_path="manifest.acf",
    )
    with warnings.catch_warnings(record=True) as recorded_warnings:
      warnings.simplefilter("always")
      srv.current_build = "300"
      srv.latest_build = "400"
      srv.last_status = "Online"

      mutation_warnings = [
          w for w in recorded_warnings if issubclass(w.category, DeprecationWarning)
      ]
      self.assertEqual(len(mutation_warnings), 3)

    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      self.assertEqual(srv.current_build, "300")
      self.assertEqual(srv.latest_build, "400")
      self.assertEqual(srv.last_status, "Online")

  def test_server_model_dict_clean_of_ephemeral_fields(self):
    srv = ServerModel(
        server_id="test-srv",
        name="Test Server",
        app_id="12345",
        manifest_path="manifest.acf",
    )
    data = srv.model_dump() if hasattr(srv, "model_dump") else srv.dict()
    self.assertNotIn("current_build", data)
    self.assertNotIn("latest_build", data)
    self.assertNotIn("last_status", data)
    self.assertNotIn("_current_build", data)
    self.assertNotIn("_latest_build", data)
    self.assertNotIn("_last_status", data)


class TestCleanErrorArchitecture(unittest.TestCase):
  """Verifies domain exception hierarchy and structured error raising without regex scraping."""

  def test_domain_exception_hierarchy(self):
    self.assertTrue(issubclass(ServerNotFoundError, NotFoundError))
    self.assertTrue(issubclass(NotFoundError, DomainError))
    self.assertTrue(issubclass(UnauthorizedError, DomainError))
    self.assertTrue(issubclass(ConflictError, DomainError))
    self.assertTrue(issubclass(ValidationError, DomainError))
    self.assertTrue(issubclass(PterodactylApiError, DomainError))

  def test_operation_result_raises_not_found(self):
    res1 = OperationResult(success=False, error="Target not found", status_code=404)
    with self.assertRaises(NotFoundError):
      res1.raise_if_failed()

    res2 = OperationResult(success=False, error="Server srv-1 not found", error_type="ServerNotFound", status_code=404)
    with self.assertRaises(ServerNotFoundError):
      res2.raise_if_failed(server_id="srv-1")

  def test_operation_result_raises_unauthorized(self):
    res1 = OperationResult(success=False, error="Bad API Key", status_code=401)
    with self.assertRaises(UnauthorizedError):
      res1.raise_if_failed()

    res2 = OperationResult(success=False, error="Forbidden", status_code=403)
    with self.assertRaises(UnauthorizedError):
      res2.raise_if_failed()

  def test_operation_result_raises_conflict(self):
    res = OperationResult(success=False, error="Resource locked", status_code=409)
    with self.assertRaises(ConflictError):
      res.raise_if_failed()

  def test_operation_result_raises_validation_error(self):
    res1 = OperationResult(success=False, error="Invalid field", status_code=422)
    with self.assertRaises(ValidationError):
      res1.raise_if_failed()

    res2 = OperationResult(success=False, error="Validation failed", error_type="ValidationError")
    with self.assertRaises(ValidationError):
      res2.raise_if_failed()

  def test_operation_result_generic_status_code(self):
    res = OperationResult(success=False, error="Server error", status_code=502)
    with self.assertRaises(PterodactylApiError) as ctx:
      res.raise_if_failed()
    self.assertEqual(ctx.exception.status_code, 502)

  def test_local_build_result_structured_raising(self):
    res_401 = LocalBuildResult(build_id=None, error="Unauthorized", status_code=401)
    with self.assertRaises(UnauthorizedError) as ctx:
      res_401.raise_if_failed()
    self.assertEqual(ctx.exception.status_code, 401)

    with self.assertRaises(ConflictError):
      res_401.raise_if_failed(exc_cls=ConflictError)

    res_404 = LocalBuildResult(build_id=None, error="Manifest missing", status_code=404)
    with self.assertRaises(NotFoundError) as ctx_nf:
      res_404.raise_if_failed()
    self.assertEqual(ctx_nf.exception.status_code, 404)

    with self.assertRaises(ServerNotFoundError) as ctx_snf:
      res_404.raise_if_failed(server_id="srv-1")
    self.assertEqual(ctx_snf.exception.status_code, 404)
    self.assertEqual(ctx_snf.exception.server_id, "srv-1")

    res_409 = LocalBuildResult(build_id=None, error="File locked", status_code=409)
    with self.assertRaises(ConflictError) as ctx_c:
      res_409.raise_if_failed()
    self.assertEqual(ctx_c.exception.status_code, 409)

    res_422 = LocalBuildResult(build_id=None, error="Bad path format", status_code=422)
    with self.assertRaises(ValidationError) as ctx_v:
      res_422.raise_if_failed()
    self.assertEqual(ctx_v.exception.status_code, 422)

    res_500 = LocalBuildResult(build_id=None, error="Server error", status_code=500)
    with self.assertRaises(PterodactylApiError) as ctx_p:
      res_500.raise_if_failed()
    self.assertEqual(ctx_p.exception.status_code, 500)

  def test_server_name_result_structured_raising(self):
    res_401 = ServerNameResult(name=None, error="Invalid API token", status_code=401)
    with self.assertRaises(UnauthorizedError) as ctx:
      res_401.raise_if_failed()
    self.assertEqual(ctx.exception.status_code, 401)

    with self.assertRaises(ConflictError):
      res_401.raise_if_failed(exc_cls=ConflictError)

    res_404 = ServerNameResult(name=None, error="Panel node missing", status_code=404)
    with self.assertRaises(NotFoundError) as ctx_nf:
      res_404.raise_if_failed()
    self.assertEqual(ctx_nf.exception.status_code, 404)

    with self.assertRaises(ServerNotFoundError) as ctx_snf:
      res_404.raise_if_failed(server_id="srv-test")
    self.assertEqual(ctx_snf.exception.status_code, 404)
    self.assertEqual(ctx_snf.exception.server_id, "srv-test")

    res_502 = ServerNameResult(name=None, error="Bad gateway", status_code=502)
    with self.assertRaises(PterodactylApiError) as ctx_p:
      res_502.raise_if_failed()
    self.assertEqual(ctx_p.exception.status_code, 502)

  def test_no_regex_scraping_from_error_string(self):
    res = OperationResult(success=False, error="Panel HTTP 500: Server exploded")
    with self.assertRaises(PterodactylApiError) as ctx:
      res.raise_if_failed()
    self.assertEqual(ctx.exception.status_code, 400)


class TestRuntimeStateReconciliation(unittest.TestCase):
  """Dedicated unit tests for RuntimeStateStore.reconcile_with_servers."""

  def setUp(self):
    self.store = RuntimeStateStore()

  def test_reconcile_retains_surviving_servers(self):
    self.store.update_server_state("srv-1", current_build="100", last_status="Online")
    self.store.update_server_state("srv-2", current_build="200", last_status="Updating")

    servers = [
        ServerModel(server_id="srv-1", name="Server 1"),
        ServerModel(server_id="srv-2", name="Server 2"),
    ]
    self.store.reconcile_with_servers(servers)

    st1 = self.store.get_server_state("srv-1")
    st2 = self.store.get_server_state("srv-2")
    self.assertEqual(st1.current_build, "100")
    self.assertEqual(st1.last_status, "Online")
    self.assertEqual(st2.current_build, "200")
    self.assertEqual(st2.last_status, "Updating")

  def test_reconcile_prunes_removed_servers(self):
    self.store.update_server_state("srv-1", current_build="100")
    self.store.update_server_state("srv-removed", current_build="999")

    servers = [ServerModel(server_id="srv-1", name="Server 1")]
    self.store.reconcile_with_servers(servers)

    all_states = self.store.get_all_server_states()
    self.assertIn("srv-1", all_states)
    self.assertNotIn("srv-removed", all_states)

  def test_reconcile_initializes_default_for_new_servers(self):
    servers = [
        ServerModel(server_id="srv-new", name="New Server"),
    ]
    self.store.reconcile_with_servers(servers)

    all_states = self.store.get_all_server_states()
    self.assertIn("srv-new", all_states)
    new_state = all_states["srv-new"]
    self.assertEqual(new_state.server_id, "srv-new")
    self.assertEqual(new_state.current_build, "Unknown")
    self.assertEqual(new_state.latest_build, "Unknown")
    self.assertEqual(new_state.last_status, ServerUpdateStatus.IDLE)

  def test_reconcile_handles_case_insensitivity(self):
    self.store.update_server_state("srv-case", current_build="555")
    servers = [ServerModel(server_id="SRV-CASE", name="Case Server")]
    self.store.reconcile_with_servers(servers)

    all_states = self.store.get_all_server_states()
    self.assertIn("srv-case", all_states)
    self.assertEqual(all_states["srv-case"].current_build, "555")

  def test_reconcile_empty_server_list_cleans_all(self):
    self.store.update_server_state("srv-1", current_build="100")
    self.store.update_server_state("srv-2", current_build="200")
    self.store.reconcile_with_servers([])
    self.assertEqual(len(self.store.get_all_server_states()), 0)

  def test_reconcile_ignores_whitespace_only_server_id(self):
    servers = [
        ServerModel(server_id="   ", name="Whitespace Server"),
        ServerModel(server_id="srv-real", name="Real Server"),
    ]
    self.store.reconcile_with_servers(servers)
    all_states = self.store.get_all_server_states()
    self.assertIn("srv-real", all_states)
    self.assertNotIn("", all_states)
    self.assertNotIn("   ", all_states)

  def test_reconcile_preserves_ephemeral_telemetry_on_new_servers(self):
    srv = ServerModel(server_id="srv-seeded", name="Seeded")
    object.__setattr__(srv, "_ephemeral_current_build", "3333")
    object.__setattr__(srv, "_ephemeral_latest_build", "4444")
    object.__setattr__(srv, "_ephemeral_last_status", "Active")
    self.store.reconcile_with_servers([srv])
    st = self.store.get_server_state("srv-seeded")
    self.assertEqual(st.current_build, "3333")
    self.assertEqual(st.latest_build, "4444")
    self.assertEqual(st.last_status, "Active")


class TestRuntimeStateStoreLifecycleSync(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.store = RuntimeStateStore()

  def test_remove_and_delete_server_state(self):
    self.store.update_server_state("srv1", current_build="100", latest_build="200")
    self.store.update_server_state("srv2", current_build="300", latest_build="400")
    self.assertIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv2", self.store.get_all_server_states())

    self.store.remove_server_state("srv1")
    self.assertNotIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv2", self.store.get_all_server_states())

    self.store.delete_server_state("srv2")
    self.assertNotIn("srv2", self.store.get_all_server_states())

  def test_server_service_save_settings_synchronizes_runtime_state(self):
    repo = MagicMock()
    repo.load.return_value = AppConfigModel(servers=[ServerModel(server_id="srv1")])
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("srv1", current_build="100")
    self.store.update_server_state("srv_deprecated", current_build="999")
    self.assertIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv_deprecated", self.store.get_all_server_states())

    new_settings = SettingsUpdateDTO(
        servers=[
            ServerModel(server_id="srv1", name="Server 1"),
            ServerModel(server_id="srv2", name="Server 2"),
        ]
    )
    service.save_settings(new_settings)

    all_states = self.store.get_all_server_states()
    self.assertIn("srv1", all_states)
    self.assertIn("srv2", all_states)
    self.assertNotIn("srv_deprecated", all_states)

  def test_server_service_delete_server_cleans_runtime_state(self):
    repo = MagicMock()
    srv1 = ServerModel(server_id="srv1", name="Server 1")
    srv2 = ServerModel(server_id="srv2", name="Server 2")
    cfg = AppConfigModel(servers=[srv1, srv2])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("srv1", current_build="100")
    self.store.update_server_state("srv2", current_build="200")

    settings = SettingsUpdateDTO(servers=[srv1, srv2])
    service.delete_server("srv1", settings)

    all_states = self.store.get_all_server_states()
    self.assertNotIn("srv1", all_states)
    self.assertIn("srv2", all_states)

  async def test_server_service_save_single_server_updates_id_in_runtime_state(self):
    repo = MagicMock()
    srv = ServerModel(server_id="old_srv", name="Initial")
    cfg = AppConfigModel(servers=[srv])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("old_srv", current_build="555")

    await service.save_single_server("old_srv", {"server_id": "new_srv", "name": "Renamed"})

    all_states = self.store.get_all_server_states()
    self.assertNotIn("old_srv", all_states)
    self.assertIn("new_srv", all_states)
    self.assertEqual(all_states["new_srv"].current_build, "555")

  def test_runtime_state_store_rename_server_state(self):
    self.store.update_server_state("srv-a", current_build="100", latest_build="200", last_status=ServerUpdateStatus.UP_TO_DATE)
    renamed = self.store.rename_server_state("srv-a", "srv-b")
    self.assertIsNotNone(renamed)
    self.assertEqual(renamed.server_id, "srv-b")
    self.assertEqual(renamed.current_build, "100")
    self.assertEqual(renamed.latest_build, "200")
    self.assertEqual(renamed.last_status, ServerUpdateStatus.UP_TO_DATE)

    states = self.store.get_all_server_states()
    self.assertNotIn("srv-a", states)
    self.assertIn("srv-b", states)

  async def test_server_service_sync_server_name_migrates_runtime_state(self):
    repo = MagicMock()
    srv = ServerModel(server_id="srv-initial", name="Old Box")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="testkey", servers=[srv])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    ptero.get_server_name.return_value = MagicMock(name="Synced Box")
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("srv-initial", current_build="777", latest_build="888")
    await service.sync_server_name("srv-initial", server_id_override="srv-overridden")

    states = self.store.get_all_server_states()
    self.assertNotIn("srv-initial", states)
    self.assertIn("srv-overridden", states)
    self.assertEqual(states["srv-overridden"].current_build, "777")
    self.assertEqual(states["srv-overridden"].latest_build, "888")

  def test_server_service_add_server_synchronizes_runtime_state(self):
    repo = MagicMock()
    cfg = AppConfigModel(servers=[ServerModel(server_id="srv-keep")])
    repo.load.return_value = cfg
    service = ServerService(
        repository=repo,
        ptero=AsyncMock(),
        steam=AsyncMock(),
        simulator_store=MagicMock(),
        countdown=MagicMock(),
        runtime_state=self.store,
    )

    self.store.update_server_state("srv-keep", current_build="111")
    self.store.update_server_state("srv-stale", current_build="999")

    new_settings = SettingsUpdateDTO(servers=[ServerModel(server_id="srv-keep")])
    service.add_server(new_settings)

    states = self.store.get_all_server_states()
    self.assertIn("srv-keep", states)
    self.assertNotIn("srv-stale", states)


class TestServiceFindServerIndexDelegation(unittest.TestCase):
  """Verifies ServerConfigService and ServerPowerService delegate find_server_index."""

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.countdown = MagicMock()
    self.servers = [
        ServerModel(server_id="srv-alpha", name="Alpha"),
        ServerModel(server_id="srv-beta", name="Beta"),
    ]
    self.cfg = AppConfigModel(servers=self.servers)
    self.repo.load.return_value = self.cfg
    self.config_service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
    )
    self.power_service = ServerPowerService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
    )

  def test_config_service_find_server_index_with_list(self):
    self.assertEqual(self.config_service.find_server_index(self.servers, "srv-alpha"), 0)
    self.assertEqual(self.config_service.find_server_index(self.servers, "SRV-BETA"), 1)
    self.assertEqual(self.config_service.find_server_index(self.servers, 1), 1)
    self.assertIsNone(self.config_service.find_server_index(self.servers, "unknown"))

  def test_config_service_find_server_index_with_app_config_model(self):
    self.assertEqual(self.config_service.find_server_index(self.cfg, "srv-beta"), 1)
    self.assertEqual(self.config_service.find_server_index(self.cfg, 0), 0)

  def test_config_service_find_server_index_single_argument_delegates_to_repo(self):
    self.assertEqual(self.config_service.find_server_index("srv-beta"), 1)
    self.assertEqual(self.config_service.find_server_index(0), 0)
    self.assertIsNone(self.config_service.find_server_index("unknown"))

  def test_power_service_find_server_index_with_list(self):
    self.assertEqual(self.power_service.find_server_index(self.servers, "srv-alpha"), 0)
    self.assertEqual(self.power_service.find_server_index(self.servers, "SRV-BETA"), 1)
    self.assertEqual(self.power_service.find_server_index(self.servers, 1), 1)
    self.assertIsNone(self.power_service.find_server_index(self.servers, "unknown"))

  def test_power_service_find_server_index_with_app_config_model(self):
    self.assertEqual(self.power_service.find_server_index(self.cfg, "srv-beta"), 1)
    self.assertEqual(self.power_service.find_server_index(self.cfg, 0), 0)

  def test_power_service_find_server_index_single_argument_delegates_to_repo(self):
    self.assertEqual(self.power_service.find_server_index("srv-beta"), 1)
    self.assertEqual(self.power_service.find_server_index(0), 0)
    self.assertIsNone(self.power_service.find_server_index("unknown"))


class TestOfflineSaveSingleServerPersistence(unittest.IsolatedAsyncioTestCase):
  """Verifies save_single_server behaves as an atomic local persistence operation decoupled from live panel network queries."""

  def setUp(self):
    self.initial_servers = [
        ServerModel(
            server_id="srv-1",
            name="Existing Server Name",
            app_id="896660",
            manifest_path="steamapps/appmanifest_896660.acf",
            query_port_offset=0,
            broadcast_command_template="say {message}",
        )
    ]
    self.cfg = AppConfigModel(
        panel_url="https://panel.example.com",
        api_key="secret-key",
        servers=self.initial_servers,
    )
    self.repo = MagicMock()
    self.repo.load.return_value = self.cfg
    self.ptero = AsyncMock()
    self.ptero.get_server_name.side_effect = AssertionError("get_server_name should not be called during save_single_server")

    self.runtime_state = RuntimeStateStore()
    self.service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=AsyncMock(),
        runtime_state=self.runtime_state,
    )

  async def test_save_single_server_does_not_call_ptero_and_preserves_name_if_empty(self):
    req = SingleServerSaveRequest(
        server_id="srv-1",
        name="",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
        query_port_offset=5,
    )
    updated = await self.service.save_single_server("srv-1", req)

    self.assertEqual(updated.name, "Existing Server Name")
    self.assertEqual(updated.query_port_offset, 5)
    self.repo.save.assert_called_once()
    self.ptero.get_server_name.assert_not_called()

  async def test_save_single_server_updates_name_when_provided(self):
    req = SingleServerSaveRequest(
        server_id="srv-1",
        name="User Typed New Name",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
    )
    updated = await self.service.save_single_server("srv-1", req)

    self.assertEqual(updated.name, "User Typed New Name")
    self.repo.save.assert_called_once()
    self.ptero.get_server_name.assert_not_called()

  async def test_save_single_server_offline_with_dict(self):
    data = {
        "server_id": "srv-1",
        "name": "",
        "query_port_offset": 10,
    }
    updated = await self.service.save_single_server("srv-1", data)

    self.assertEqual(updated.name, "Existing Server Name")
    self.assertEqual(updated.query_port_offset, 10)
    self.ptero.get_server_name.assert_not_called()

  async def test_sync_name_initializes_runtime_state_for_previously_unconfigured_server(self):
    self.cfg.servers.append(ServerModel(server_id="", name="New Server"))
    self.ptero.get_server_name.side_effect = None
    self.ptero.get_server_name.return_value = ServerNameResult(name="Ptero Server", error=None)

    name = await self.service.sync_server_name(1, server_id_override="srv-brand-new")
    self.assertEqual(name, "Ptero Server")
    self.assertEqual(self.cfg.servers[1].server_id, "srv-brand-new")
    self.assertIn("srv-brand-new", self.runtime_state.get_all_server_states())


if __name__ == "__main__":
  unittest.main()
