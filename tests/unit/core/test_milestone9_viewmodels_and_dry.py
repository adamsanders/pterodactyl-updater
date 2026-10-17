import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.models import (
    AppConfigModel,
    DetectedServerDetails,
    PowerSignal,
    PowerState,
    ServerModel,
    ServerRuntimeState,
    ServerUpdateStatus,
    SteamSearchResult,
)
from app.core.protocols import CountdownManagerProtocol
from app.main import app
from app.services.runtime_state import RuntimeStateStore
from app.services.server_config_service import ServerConfigService
from app.services.server_power_service import ServerPowerService
from app.web.schemas import (
    DashboardViewModel,
    LookupNameResponse,
    PowerActionResponse,
    ServerCardViewModel,
    SingleServerSaveRequest,
    WebhookPreview,
)


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
    # "0" matches server_id "0" at index 1, NOT numeric index 0
    self.assertEqual(cfg_special.find_server_index("0"), 1)


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
    # Pterodactyl gateway should NOT be called; raise if invoked to prove decoupling
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
        name="",  # user did not change name
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
    from app.core.models import ServerNameResult
    self.cfg.servers.append(ServerModel(server_id="", name="New Server"))
    self.ptero.get_server_name.side_effect = None
    self.ptero.get_server_name.return_value = ServerNameResult(name="Ptero Server", error=None)

    name = await self.service.sync_server_name(1, server_id_override="srv-brand-new")
    self.assertEqual(name, "Ptero Server")
    self.assertEqual(self.cfg.servers[1].server_id, "srv-brand-new")
    self.assertIn("srv-brand-new", self.runtime_state.get_all_server_states())


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
        app_version="1.26.0",
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
    self.assertEqual(dvm.version, "1.26.0")
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
        app_version="1.26.0",
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


class TestStronglyTypedRouteResponses(unittest.TestCase):
  """Unit tests verifying strongly typed route response schemas and annotations."""

  def test_fastapi_route_response_model_annotations(self):
    # Find routes on FastAPI app
    route_models = {}
    for r in app.routes:
      if hasattr(r, "path") and hasattr(r, "response_model"):
        methods = tuple(r.methods) if hasattr(r, "methods") else ()
        route_models[(r.path, methods)] = r.response_model

    # Check detect-details endpoint
    self.assertIn(("/api/servers/detect-details", ("GET",)), route_models)
    self.assertIs(route_models[("/api/servers/detect-details", ("GET",))], DetectedServerDetails)

    # Check lookup-name endpoint
    self.assertIn(("/api/servers/lookup-name", ("GET",)), route_models)
    self.assertIs(route_models[("/api/servers/lookup-name", ("GET",))], LookupNameResponse)

    # Check steam/search endpoint
    self.assertIn(("/api/steam/search", ("GET",)), route_models)
    self.assertEqual(route_models[("/api/steam/search", ("GET",))], list[SteamSearchResult])

    # Check power action endpoint
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
    # Configure test client with mocked services
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
