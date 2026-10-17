import unittest
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.core.exceptions import (
    A2SQueryError,
    ConfigurationError,
    DomainError,
    InvalidPowerActionError,
    NotificationError,
    PterodactylApiError,
    ServerNotFoundError,
    SimulationError,
    SteamApiError,
)
from app.core.models import (
    DetectedServerDetails,
    LocalBuildResult,
    OperationResult,
    PlayerMetrics,
    PowerSignal,
    PowerState,
    PowerTrackerEntry,
    ServerAllocation,
    ServerModel,
    ServerNameResult,
    ServerStatusDTO,
    SteamSearchResult,
)
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.steam import SteamAdapter
from app.adapters.a2s import A2SAdapter


class TestDomainModels(unittest.TestCase):

  def test_server_allocation_attributes_and_unpacking(self):
    alloc = ServerAllocation(ip="192.168.1.100", port=2456)
    self.assertEqual(alloc.ip, "192.168.1.100")
    self.assertEqual(alloc.port, 2456)

    # Verify tuple unpacking compatibility
    ip, port = alloc
    self.assertEqual(ip, "192.168.1.100")
    self.assertEqual(port, 2456)

    # Defaults
    default_alloc = ServerAllocation()
    self.assertIsNone(default_alloc.ip)
    self.assertIsNone(default_alloc.port)

  def test_player_metrics_attributes_and_unpacking(self):
    metrics = PlayerMetrics(current=5, max=64)
    self.assertEqual(metrics.current, 5)
    self.assertEqual(metrics.max, 64)

    # Verify tuple unpacking compatibility
    curr, max_p = metrics
    self.assertEqual(curr, 5)
    self.assertEqual(max_p, 64)

    # Defaults
    default_metrics = PlayerMetrics()
    self.assertIsNone(default_metrics.current)
    self.assertIsNone(default_metrics.max)

  def test_local_build_result_attributes_and_unpacking(self):
    res = LocalBuildResult(build_id="12345678", error=None)
    self.assertEqual(res.build_id, "12345678")
    self.assertIsNone(res.error)

    # Tuple unpacking
    b_id, err = res
    self.assertEqual(b_id, "12345678")
    self.assertIsNone(err)

    # raise_if_failed success
    self.assertEqual(res.raise_if_failed(), "12345678")

    # Error case with structured status_code and error_type
    err_res = LocalBuildResult(
        build_id=None,
        error="Manifest missing",
        status_code=404,
        error_type="NotFound",
    )
    self.assertIsNone(err_res.build_id)
    self.assertEqual(err_res.error, "Manifest missing")
    self.assertEqual(err_res.status_code, 404)
    self.assertEqual(err_res.error_type, "NotFound")
    with self.assertRaises(ServerNotFoundError) as ctx:
      err_res.raise_if_failed(server_id="srv1")
    self.assertEqual(ctx.exception.status_code, 404)
    self.assertEqual(ctx.exception.server_id, "srv1")

    # Explicit status_code override
    with self.assertRaises(PterodactylApiError) as ctx_override:
      err_res.raise_if_failed(status_code=500, server_id="srv1")
    self.assertEqual(ctx_override.exception.status_code, 500)

    # Safe fallback parsing when status_code is None (default to 400 without regex scraping)
    legacy_err = LocalBuildResult(build_id=None, error="Panel HTTP 403: Forbidden")
    with self.assertRaises(PterodactylApiError) as ctx_legacy:
      legacy_err.raise_if_failed()
    self.assertEqual(ctx_legacy.exception.status_code, 400)

  def test_server_name_result_attributes_and_unpacking(self):
    res = ServerNameResult(name="My Server", error=None, status_code=200)
    self.assertEqual(res.name, "My Server")
    self.assertIsNone(res.error)
    self.assertEqual(res.status_code, 200)

    # Tuple unpacking
    name, err = res
    self.assertEqual(name, "My Server")
    self.assertIsNone(err)

    # raise_if_failed success
    self.assertEqual(res.raise_if_failed(), "My Server")

    # Error case with structured status_code
    err_res = ServerNameResult(
        name=None,
        error="Server disappeared",
        status_code=404,
        error_type="NotFound",
    )
    self.assertIsNone(err_res.name)
    self.assertEqual(err_res.error, "Server disappeared")
    self.assertEqual(err_res.status_code, 404)
    self.assertEqual(err_res.error_type, "NotFound")
    with self.assertRaises(ServerNotFoundError) as ctx:
      err_res.raise_if_failed(server_id="srv_test")
    self.assertEqual(ctx.exception.status_code, 404)
    self.assertEqual(ctx.exception.server_id, "srv_test")

    # Explicit status_code override
    with self.assertRaises(PterodactylApiError) as ctx_override:
      err_res.raise_if_failed(status_code=502, server_id="srv_test")
    self.assertEqual(ctx_override.exception.status_code, 502)

    # Safe fallback parsing when status_code is None (default to 400 without regex scraping)
    legacy_res = ServerNameResult(name=None, error="Panel HTTP 503: Unavailable")
    with self.assertRaises(PterodactylApiError) as ctx_legacy:
      legacy_res.raise_if_failed()
    self.assertEqual(ctx_legacy.exception.status_code, 400)

  def test_operation_result_attributes_and_unpacking(self):
    res = OperationResult(success=True, error=None, status_code=204)
    self.assertTrue(res.success)
    self.assertIsNone(res.error)
    self.assertEqual(res.status_code, 204)
    self.assertTrue(bool(res))

    # Tuple unpacking
    success, err = res
    self.assertTrue(success)
    self.assertIsNone(err)

    # raise_if_failed on success
    self.assertIs(res.raise_if_failed(), res)

    # Failure case with structured status_code and error_type
    fail_res = OperationResult(
        success=False,
        error="Power node offline",
        status_code=500,
        error_type="HttpError",
    )
    self.assertFalse(fail_res.success)
    self.assertEqual(fail_res.error, "Power node offline")
    self.assertEqual(fail_res.status_code, 500)
    self.assertEqual(fail_res.error_type, "HttpError")
    self.assertFalse(bool(fail_res))

    with self.assertRaises(PterodactylApiError) as ctx:
      fail_res.raise_if_failed(server_id="srv5")
    self.assertEqual(ctx.exception.status_code, 500)
    self.assertEqual(ctx.exception.server_id, "srv5")

    # Automatic classification by error_type
    invalid_power = OperationResult(
        success=False,
        error="Unknown action foo",
        status_code=400,
        error_type="InvalidPowerAction",
    )
    with self.assertRaises(InvalidPowerActionError) as ctx_inv:
      invalid_power.raise_if_failed()
    self.assertEqual(ctx_inv.exception.status_code, 400)

    server_not_found = OperationResult(
        success=False,
        error="No such server",
        status_code=404,
        error_type="ServerNotFound",
    )
    with self.assertRaises(ServerNotFoundError) as ctx_snf:
      server_not_found.raise_if_failed(server_id="missing_srv")
    self.assertEqual(ctx_snf.exception.status_code, 404)
    self.assertEqual(ctx_snf.exception.server_id, "missing_srv")

    config_err = OperationResult(
        success=False,
        error="Server ID or Panel API Key configuration is incomplete.",
        status_code=400,
        error_type="ConfigurationError",
    )
    with self.assertRaises(ConfigurationError) as ctx_cfg:
      config_err.raise_if_failed()
    self.assertEqual(ctx_cfg.exception.status_code, 400)

    # Explicit status_code override
    with self.assertRaises(PterodactylApiError) as ctx_override:
      fail_res.raise_if_failed(status_code=503, server_id="srv5")
    self.assertEqual(ctx_override.exception.status_code, 503)

    # Safe fallback parsing when status_code is None (default to 400 without regex scraping)
    legacy_op = OperationResult(success=False, error="Panel HTTP 500: Server crashed")
    with self.assertRaises(PterodactylApiError) as ctx_legacy:
      legacy_op.raise_if_failed()
    self.assertEqual(ctx_legacy.exception.status_code, 400)


class TestDomainExceptions(unittest.TestCase):

  def test_domain_error_hierarchy(self):
    self.assertTrue(issubclass(PterodactylApiError, DomainError))
    self.assertTrue(issubclass(SteamApiError, DomainError))
    self.assertTrue(issubclass(A2SQueryError, DomainError))
    self.assertTrue(issubclass(ConfigurationError, DomainError))
    self.assertTrue(issubclass(NotificationError, DomainError))
    self.assertTrue(issubclass(ServerNotFoundError, DomainError))
    self.assertTrue(issubclass(InvalidPowerActionError, DomainError))
    self.assertTrue(issubclass(SimulationError, DomainError))
    self.assertTrue(issubclass(DomainError, Exception))

  def test_server_model_purges_ignored_redistributable_appids(self):
    data = {
        "name": "Enshrouded Server",
        "server_id": "srv2",
        "app_id": "1007",
        "manifest_path": "steamapps/appmanifest_1007.acf",
    }
    srv = ServerModel(**data)
    self.assertEqual(srv.app_id, "")
    self.assertEqual(srv.manifest_path, "")

  def test_server_model_corrects_manifest_path_with_valid_appid_and_1007_manifest(self):
    data = {
        "name": "Valheim Server",
        "server_id": "srv1",
        "app_id": "896660",
        "manifest_path": "steamapps/appmanifest_1007.acf",
    }
    srv = ServerModel(**data)
    self.assertEqual(srv.app_id, "896660")
    self.assertEqual(srv.manifest_path, "steamapps/appmanifest_896660.acf")

  def test_server_model_slider_defaults_are_off(self):
    srv = ServerModel()
    self.assertFalse(srv.auto_restart)
    self.assertFalse(srv.discord_alerts)
    self.assertFalse(srv.warn_ingame_countdown)
    self.assertFalse(srv.warn_discord_countdown)

  def test_pterodactyl_api_error_attributes(self):
    err = PterodactylApiError(
        "Server not found", status_code=404, server_id="srv-123", details="Resource missing"
    )
    self.assertEqual(str(err), "Server not found")
    self.assertEqual(err.status_code, 404)
    self.assertEqual(err.server_id, "srv-123")
    self.assertEqual(err.details, "Resource missing")

  def test_steam_api_error_attributes(self):
    err = SteamApiError("Steam API rate limited", app_id="896660")
    self.assertEqual(str(err), "Steam API rate limited")
    self.assertEqual(err.app_id, "896660")
    self.assertEqual(err.status_code, 502)

  def test_a2s_query_error(self):
    err = A2SQueryError("Socket timeout connecting to server")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(str(err), "Socket timeout connecting to server")
    self.assertEqual(err.status_code, 504)

  def test_configuration_error(self):
    err = ConfigurationError("Corrupted config.json format")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(str(err), "Corrupted config.json format")
    self.assertEqual(err.status_code, 400)

  def test_server_not_found_error(self):
    err = ServerNotFoundError("Server 'srv-404' not found in configuration", server_id="srv-404")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 404)
    self.assertEqual(err.server_id, "srv-404")

  def test_invalid_power_action_error(self):
    err = InvalidPowerActionError("Invalid signal 'explode'", action="explode")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 400)
    self.assertEqual(err.action, "explode")

  def test_simulation_error(self):
    err = SimulationError("Simulated build failed", server_id="srv-1")
    self.assertIsInstance(err, DomainError)
    self.assertEqual(err.status_code, 400)
    self.assertEqual(err.server_id, "srv-1")

  def test_notification_error_attributes(self):
    err = NotificationError(
        "Discord webhook delivery failed",
        status_code=500,
        details="Internal Server Error",
    )
    self.assertIsInstance(err, DomainError)
    self.assertEqual(str(err), "Discord webhook delivery failed")
    self.assertEqual(err.status_code, 500)
    self.assertEqual(err.details, "Internal Server Error")


class TestAdapterTypedReturns(unittest.IsolatedAsyncioTestCase):

  async def test_pterodactyl_adapter_returns_typed_models(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)

    # 1. get_server_name
    mock_client.get.return_value = MagicMock(
        status_code=200, json=lambda: {"attributes": {"name": "Dedicated Box"}}
    )
    name_res = await adapter.get_server_name("http://panel", "key", "srv1")
    self.assertIsInstance(name_res, ServerNameResult)
    self.assertEqual(name_res.name, "Dedicated Box")
    self.assertIsNone(name_res.error)
    self.assertEqual(name_res.status_code, 200)

    # 2. get_server_allocation
    mock_client.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "attributes": {
                "relationships": {
                    "allocations": {
                        "data": [
                            {"attributes": {"is_default": True, "ip": "10.0.0.5", "port": 7777}}
                        ]
                    }
                }
            }
        },
    )
    alloc_res = await adapter.get_server_allocation("http://panel", "key", "srv1")
    self.assertIsInstance(alloc_res, ServerAllocation)
    self.assertEqual(alloc_res.ip, "10.0.0.5")
    self.assertEqual(alloc_res.port, 7777)

    # 3. get_local_build
    mock_client.get.return_value = MagicMock(
        status_code=200, text='"AppState"\n{\n\t"buildid"\t\t"998877"\n}'
    )
    build_res = await adapter.get_local_build("http://panel", "key", "srv1", "steamapps/manifest.acf")
    self.assertIsInstance(build_res, LocalBuildResult)
    self.assertEqual(build_res.build_id, "998877")
    self.assertIsNone(build_res.error)
    self.assertEqual(build_res.status_code, 200)

    # 4. send_power_signal
    mock_client.post.return_value = MagicMock(status_code=204)
    power_res = await adapter.send_power_signal("http://panel", "key", "srv1", "restart")
    self.assertIsInstance(power_res, OperationResult)
    self.assertTrue(power_res.success)
    self.assertIsNone(power_res.error)
    self.assertEqual(power_res.status_code, 204)

    # 5. rename_server
    mock_client.post.return_value = MagicMock(status_code=200)
    rename_res = await adapter.rename_server("http://panel", "key", "srv1", "New Name")
    self.assertIsInstance(rename_res, OperationResult)
    self.assertTrue(rename_res.success)
    self.assertIsNone(rename_res.error)
    self.assertEqual(rename_res.status_code, 200)

    # 6. Structured error results without raising
    mock_client.get.return_value = MagicMock(status_code=404)
    name_err = await adapter.get_server_name("http://panel", "key", "srv1", raise_on_error=False)
    self.assertEqual(name_err.status_code, 404)
    self.assertEqual(name_err.error_type, "NotFound")

    mock_client.post.return_value = MagicMock(status_code=500, text="Internal error")
    power_err = await adapter.send_power_signal("http://panel", "key", "srv1", "restart", raise_on_error=False)
    self.assertEqual(power_err.status_code, 500)
    self.assertEqual(power_err.error_type, "HttpError")

    # 7. Server name missing in attributes with 200 OK
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"attributes": {}})
    name_parse_err = await adapter.get_server_name("http://panel", "key", "srv1", raise_on_error=False)
    self.assertIsNone(name_parse_err.name)
    self.assertEqual(name_parse_err.status_code, 200)
    self.assertEqual(name_parse_err.error_type, "ParseError")

  async def test_pterodactyl_adapter_raise_on_error(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)

    # Power signal failure with raise_on_error=True
    mock_client.post.return_value = MagicMock(status_code=500, text="Internal Panel Error")
    with self.assertRaises(PterodactylApiError) as ctx:
      await adapter.send_power_signal(
          "http://panel", "key", "srv1", "restart", raise_on_error=True
      )
    self.assertEqual(ctx.exception.server_id, "srv1")
    self.assertEqual(ctx.exception.status_code, 500)

    # get_local_build failure with raise_on_error=True
    mock_client.get.return_value = MagicMock(status_code=404, text="File Not Found")
    with self.assertRaises(PterodactylApiError) as ctx:
      await adapter.get_local_build(
          "http://panel", "key", "srv1", "manifest.acf", raise_on_error=True
      )
    self.assertEqual(ctx.exception.server_id, "srv1")
    self.assertEqual(ctx.exception.status_code, 404)

  async def test_steam_adapter_raise_on_error(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = SteamAdapter(mock_client)

    # SteamCMD API failure with raise_on_error=True
    mock_client.get.return_value = MagicMock(status_code=500, text="Server Error")
    with self.assertRaises(SteamApiError) as ctx:
      await adapter.get_latest_build("896660", raise_on_error=True)
    self.assertEqual(ctx.exception.app_id, "896660")
    self.assertEqual(ctx.exception.status_code, 500)

  async def test_a2s_adapter_returns_player_metrics(self):
    adapter = A2SAdapter()
    metrics = await adapter.get_player_count("", 0)
    self.assertIsInstance(metrics, PlayerMetrics)
    self.assertIsNone(metrics.current)
    self.assertIsNone(metrics.max)

  async def test_pterodactyl_adapter_power_state_and_signal_typing(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)

    # get_power_state returns PowerState enum instance
    mock_client.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"attributes": {"current_state": "running"}},
    )
    p_state = await adapter.get_power_state("http://panel", "key", "srv1")
    self.assertIsInstance(p_state, PowerState)
    self.assertIs(p_state, PowerState.RUNNING)
    self.assertEqual(p_state, "running")

    # send_power_signal accepts PowerSignal enum
    mock_client.post.return_value = MagicMock(status_code=204)
    res = await adapter.send_power_signal("http://panel", "key", "srv1", PowerSignal.RESTART)
    self.assertTrue(res.success)

    # send_power_signal rejects invalid signal string
    res_bad = await adapter.send_power_signal("http://panel", "key", "srv1", "invalid_action")
    self.assertFalse(res_bad.success)
    self.assertIn("Invalid power action 'invalid_action'", res_bad.error)


class TestPowerStateAndSignalEnums(unittest.TestCase):

  def test_power_state_enum_values_and_identity(self):
    self.assertEqual(PowerState.RUNNING, "running")
    self.assertEqual(PowerState.OFFLINE, "offline")
    self.assertEqual(PowerState.STARTING, "starting")
    self.assertEqual(PowerState.STOPPING, "stopping")
    self.assertEqual(PowerState.UNKNOWN, "unknown")

    self.assertEqual(
        {s.value for s in PowerState},
        {"running", "offline", "starting", "stopping", "unknown"},
    )

  def test_power_signal_enum_values_and_identity(self):
    self.assertEqual(PowerSignal.START, "start")
    self.assertEqual(PowerSignal.STOP, "stop")
    self.assertEqual(PowerSignal.RESTART, "restart")
    self.assertEqual(PowerSignal.KILL, "kill")

    self.assertEqual(
        {s.value for s in PowerSignal},
        {"start", "stop", "restart", "kill"},
    )

  def test_strenum_string_inheritance_and_formatting(self):
    self.assertIsInstance(PowerState.RUNNING, str)
    self.assertIsInstance(PowerSignal.RESTART, str)

    self.assertEqual(str(PowerState.RUNNING), "running")
    self.assertEqual(f"{PowerState.RUNNING}", "running")
    self.assertEqual(str(PowerSignal.RESTART), "restart")
    self.assertEqual(f"{PowerSignal.RESTART}", "restart")

  def test_enum_instantiation_from_str(self):
    self.assertIs(PowerState("running"), PowerState.RUNNING)
    self.assertIs(PowerState("offline"), PowerState.OFFLINE)
    self.assertIs(PowerSignal("restart"), PowerSignal.RESTART)
    self.assertIs(PowerSignal("kill"), PowerSignal.KILL)

    with self.assertRaises(ValueError):
      PowerState("invalid_state")

    with self.assertRaises(ValueError):
      PowerSignal("explode")

  def test_server_status_dto_power_state_validation(self):
    dto = ServerStatusDTO(
        idx=0,
        server_id="srv1",
        name="Server 1",
        power_state=PowerState.RUNNING,
        current_build="100",
        latest_build="100",
        last_status="Idle",
        target_timestamp=0.0,
        remaining_seconds=0,
        is_updating=False,
    )
    self.assertIs(dto.power_state, PowerState.RUNNING)
    self.assertEqual(dto.power_state, "running")

    # String value coerced by Pydantic to PowerState enum
    dto2 = ServerStatusDTO(
        idx=0,
        server_id="srv1",
        name="Server 1",
        power_state="offline",
        current_build="100",
        latest_build="100",
        last_status="Idle",
        target_timestamp=0.0,
        remaining_seconds=0,
        is_updating=False,
    )
    self.assertIs(dto2.power_state, PowerState.OFFLINE)

    # Invalid power_state string raises ValidationError
    from pydantic import ValidationError
    with self.assertRaises(ValidationError):
      ServerStatusDTO(
          idx=0,
          server_id="srv1",
          name="Server 1",
          power_state="destroyed",
          current_build="100",
          latest_build="100",
          last_status="Idle",
          target_timestamp=0.0,
          remaining_seconds=0,
          is_updating=False,
      )

  def test_power_state_and_signal_from_str_normalization(self):
    # PowerState normalization
    self.assertIs(PowerState.from_str(PowerState.RUNNING), PowerState.RUNNING)
    self.assertIs(PowerState.from_str("running"), PowerState.RUNNING)
    self.assertIs(PowerState.from_str("RUNNING"), PowerState.RUNNING)
    self.assertIs(PowerState.from_str("  running  "), PowerState.RUNNING)
    self.assertIs(PowerState.from_str("offline"), PowerState.OFFLINE)
    self.assertIs(PowerState.from_str("OFFLINE"), PowerState.OFFLINE)
    self.assertIs(PowerState.from_str("stopped"), PowerState.OFFLINE)
    self.assertIs(PowerState.from_str("STOPPED"), PowerState.OFFLINE)
    self.assertIs(PowerState.from_str("starting"), PowerState.STARTING)
    self.assertIs(PowerState.from_str("stopping"), PowerState.STOPPING)
    self.assertIs(PowerState.from_str("unknown"), PowerState.UNKNOWN)
    self.assertIs(PowerState.from_str(None), PowerState.UNKNOWN)
    self.assertIs(PowerState.from_str("gibberish_state"), PowerState.UNKNOWN)

    # PowerSignal normalization
    self.assertIs(PowerSignal.from_str(PowerSignal.START), PowerSignal.START)
    self.assertIs(PowerSignal.from_str("start"), PowerSignal.START)
    self.assertIs(PowerSignal.from_str("START"), PowerSignal.START)
    self.assertIs(PowerSignal.from_str("  start  "), PowerSignal.START)
    self.assertIs(PowerSignal.from_str("stop"), PowerSignal.STOP)
    self.assertIs(PowerSignal.from_str("STOP"), PowerSignal.STOP)
    self.assertIs(PowerSignal.from_str("restart"), PowerSignal.RESTART)
    self.assertIs(PowerSignal.from_str("RESTART"), PowerSignal.RESTART)
    self.assertIs(PowerSignal.from_str("kill"), PowerSignal.KILL)
    self.assertIs(PowerSignal.from_str("KILL"), PowerSignal.KILL)

    with self.assertRaises(ValueError):
      PowerSignal.from_str("explode")
    with self.assertRaises(ValueError):
      PowerSignal.from_str(None)

  def test_server_model_query_port_offset_defaults_and_custom(self):
    srv_default = ServerModel()
    self.assertEqual(srv_default.query_port_offset, 0)
    dumped_default = srv_default.model_dump()
    self.assertIn("query_port_offset", dumped_default)
    self.assertEqual(dumped_default["query_port_offset"], 0)

    srv_custom = ServerModel(name="Valheim Modded", server_id="srv_vmod", app_id="896660", query_port_offset=2)
    self.assertEqual(srv_custom.query_port_offset, 2)
    dumped_custom = srv_custom.model_dump()
    self.assertEqual(dumped_custom["query_port_offset"], 2)

    # Negative offset
    srv_neg = ServerModel(name="Neg Offset Game", query_port_offset=-1)
    self.assertEqual(srv_neg.query_port_offset, -1)

    # Deserialization from JSON/dict
    restored = ServerModel.model_validate({"name": "Restored", "query_port_offset": 5})
    self.assertEqual(restored.query_port_offset, 5)

    # Robustness against None, empty string, string integers, and invalid types
    self.assertEqual(ServerModel(query_port_offset=None).query_port_offset, 0)
    self.assertEqual(ServerModel(query_port_offset="").query_port_offset, 0)
    self.assertEqual(ServerModel(query_port_offset="10").query_port_offset, 10)
    self.assertEqual(ServerModel(query_port_offset="invalid").query_port_offset, 0)
    self.assertEqual(ServerModel.model_validate({"query_port_offset": None}).query_port_offset, 0)
    self.assertEqual(ServerModel.model_validate({"query_port_offset": ""}).query_port_offset, 0)

  def test_settings_update_dto_preserves_query_port_offset(self):
    from app.web.schemas import SettingsUpdateDTO
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

  def test_app_config_model_ssl_verify_default_and_custom(self):
    from app.core.models import AppConfigModel
    cfg_default = AppConfigModel()
    self.assertFalse(cfg_default.ssl_verify)

    cfg_verified = AppConfigModel(ssl_verify=True)
    self.assertTrue(cfg_verified.ssl_verify)

    dumped = cfg_verified.model_dump()
    self.assertIn("ssl_verify", dumped)
    self.assertIs(dumped["ssl_verify"], True)

    restored = AppConfigModel.model_validate({"ssl_verify": True})
    self.assertTrue(restored.ssl_verify)

  def test_settings_update_dto_ssl_verify_default_and_custom(self):
    from app.web.schemas import SettingsUpdateDTO
    dto_default = SettingsUpdateDTO()
    self.assertFalse(dto_default.ssl_verify)

    dto_verified = SettingsUpdateDTO(ssl_verify=True)
    self.assertTrue(dto_verified.ssl_verify)

    dumped = dto_verified.model_dump()
    self.assertIn("ssl_verify", dumped)
    self.assertIs(dumped["ssl_verify"], True)

    restored = SettingsUpdateDTO.model_validate({"ssl_verify": True})
    self.assertTrue(restored.ssl_verify)


class TestMilestone7DomainModels(unittest.TestCase):

  def test_detected_server_details(self):
    details = DetectedServerDetails(
        name="Enshrouded Server",
        app_id="2278520",
        manifest_path="steamapps/appmanifest_2278520.acf",
        detected=True,
        error=None,
    )
    self.assertEqual(details.name, "Enshrouded Server")
    self.assertEqual(details.app_id, "2278520")
    self.assertTrue(details.detected)
    # Dictionary access compatibility
    self.assertEqual(details["app_id"], "2278520")
    self.assertEqual(details.get("name"), "Enshrouded Server")
    self.assertEqual(details.get("missing_key", "default"), "default")
    self.assertIn("app_id", details)
    self.assertIn("manifest_path", details)
    with self.assertRaises(KeyError):
      _ = details["non_existent"]
    # Serialization
    dumped = details.model_dump()
    self.assertEqual(dumped["app_id"], "2278520")
    self.assertTrue(dumped["detected"])

  def test_steam_search_result(self):
    # Construction with app_id
    res1 = SteamSearchResult(
        app_id="2278520",
        name="Enshrouded",
        type="dedicated_server",
    )
    self.assertEqual(res1.app_id, "2278520")
    self.assertEqual(res1.appid, "2278520")
    self.assertEqual(res1["app_id"], "2278520")
    self.assertEqual(res1["appid"], "2278520")
    self.assertEqual(res1.get("app_id"), "2278520")
    self.assertEqual(res1.get("appid"), "2278520")
    self.assertIn("app_id", res1)
    self.assertIn("appid", res1)
    self.assertEqual(res1, {"app_id": "2278520", "name": "Enshrouded"})
    self.assertEqual(res1, {"appid": "2278520", "name": "Enshrouded"})

    # Construction with appid alias
    res2 = SteamSearchResult(appid="896660", name="Valheim")
    self.assertEqual(res2.app_id, "896660")
    self.assertEqual(res2.appid, "896660")

    # Serialization with exclude_none
    dumped = res1.model_dump(exclude_none=True)
    self.assertEqual(dumped, {"app_id": "2278520", "name": "Enshrouded", "type": "dedicated_server"})

  def test_power_tracker_entry(self):
    entry = PowerTrackerEntry(
        raw_state=PowerState.STARTING,
        is_transitional=True,
        effective_state=PowerState.STARTING,
        last_changed=100.0,
        stable_since=0.0,
    )
    self.assertEqual(entry.raw_state, PowerState.STARTING)
    self.assertTrue(entry.is_transitional)
    self.assertEqual(entry.effective_state, PowerState.STARTING)

    # Dictionary read/write compatibility
    self.assertEqual(entry["raw_state"], PowerState.STARTING)
    entry["cached_state"] = PowerState.RUNNING
    self.assertEqual(entry.cached_state, PowerState.RUNNING)
    self.assertEqual(entry["cached_state"], PowerState.RUNNING)
    self.assertEqual(entry.get("cached_state"), PowerState.RUNNING)
    self.assertIn("cached_state", entry)
    with self.assertRaises(KeyError):
      _ = entry["invalid_key"]


if __name__ == "__main__":
  unittest.main()

