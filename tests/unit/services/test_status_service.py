import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.catalogs import PORT_OFFSET_MAP, resolve_query_port
from app.core.config import APP_VERSION, COMMIT_CODE
from app.core.models import AppConfigModel, PowerState, ServerModel, WebhookPreview
from app.services.status_service import StatusAggregationService


class TestStatusAggregationService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.ptero.consume_startup_transition = MagicMock(return_value=False)
    self.ptero.get_server_allocation.return_value = (None, None)
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.countdown = MagicMock()
    self.preview_store = MagicMock()
    self.orchestrator = AsyncMock()
    self.a2s = AsyncMock()
    self.tracker = MagicMock()
    self.formatter = lambda text: f"<p>{text}</p>"

    self.service = StatusAggregationService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        preview_store=self.preview_store,
        orchestrator=self.orchestrator,
        a2s=self.a2s,
        call_tracker=self.tracker,
        markdown_formatter=self.formatter,
    )

  async def test_get_status_snapshot_structure(self):
    srv = ServerModel(name="Valheim Alpha", server_id="srv_valheim_1", app_id="896660")
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        last_check="2026-10-15 15:00:00",
        last_status="All servers up to date",
        test_mode=False,
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.consume_startup_transition.return_value = False
    self.ptero.get_server_allocation.return_value = ("192.168.1.50", 2456)
    self.countdown.is_running.return_value = False
    self.countdown.get_target.return_value = 0.0
    self.countdown.get_remaining.return_value = 0
    self.a2s.get_player_count.return_value = (4, 10)
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()

    self.assertEqual(snapshot["app_version"], APP_VERSION)
    self.assertEqual(snapshot["commit_code"], COMMIT_CODE)
    self.assertEqual(snapshot["last_check"], "2026-10-15 15:00:00")
    self.assertEqual(snapshot["last_status"], "All servers up to date")
    self.assertFalse(snapshot["test_mode"])
    self.assertEqual(len(snapshot["servers"]), 1)

    server_data = snapshot["servers"][0]
    self.assertEqual(server_data["name"], "Valheim Alpha")
    self.assertEqual(server_data["server_id"], "srv_valheim_1")
    self.assertEqual(server_data["power_state"], "running")
    self.assertEqual(server_data["external_ip"], "1.2.3.4")
    self.assertEqual(server_data["internal_ip"], "192.168.1.50")
    self.assertEqual(server_data["port"], 2456)
    self.assertEqual(server_data["query_port"], 2457)  # Valheim offset +1
    self.assertEqual(server_data["player_count"], 4)
    self.assertEqual(server_data["max_players"], 10)

    self.tracker.record.assert_called_once()

  async def test_get_status_snapshot_is_pure_query_without_side_effects(self):
    srv = ServerModel(name="Enshrouded", server_id="srv_enshrouded", app_id="2278520")
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "offline"
    self.ptero.consume_startup_transition.return_value = False
    self.ptero.get_server_allocation.return_value = (None, None)
    self.countdown.is_running.return_value = True
    self.countdown.get_target.return_value = 1700000000.0
    self.countdown.get_remaining.return_value = 500
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()

    # Query must be side-effect free: countdown must NOT be mutated by a GET poll
    self.countdown.stop.assert_not_called()
    # Repo save must NOT be triggered during a GET poll
    self.repo.save.assert_not_called()
    self.assertEqual(snapshot["servers"][0]["power_state"], "offline")


  async def test_preview_formatting(self):
    cfg = AppConfigModel(servers=[])
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    preview = WebhookPreview(
        server_name="Palworld",
        message="Update detected!",
        embed={"description": "Patch notes"},
        timestamp="15:30:00",
    )
    self.preview_store.get_preview.return_value = preview

    snapshot = await self.service.get_status_snapshot()
    self.assertIsNotNone(snapshot["preview"])
    self.assertEqual(snapshot["preview"]["formatted_message"], "<p>Update detected!</p>")
    self.assertEqual(snapshot["preview"]["formatted_description"], "<p>Patch notes</p>")

  async def test_offline_server_with_outdated_build_is_not_updating(self):
    srv = ServerModel(
        name="Offline Test Server",
        server_id="srv_offline_test",
        app_id="896660",
        current_build="1000",
        latest_build="2000",
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "offline"
    self.countdown.is_running.return_value = False
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertFalse(server_data["is_updating"])

  async def test_running_server_with_outdated_build_is_updating(self):
    srv = ServerModel(
        name="Running Server",
        server_id="srv_running",
        app_id="896660",
        current_build="1000",
        latest_build="2000",
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.countdown.is_running.return_value = False
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertTrue(server_data["is_updating"])

  async def test_stopped_string_telemetry_normalizes_to_offline(self):
    srv = ServerModel(
        name="Stopped Server",
        server_id="srv_stopped",
        app_id="896660",
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    # Raw 'stopped' returned from gateway/Wings must normalize safely to PowerState.OFFLINE
    self.ptero.get_power_state.return_value = "stopped"
    self.countdown.is_running.return_value = False
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertEqual(server_data["power_state"], "offline")

  async def test_status_service_respects_custom_query_port_offset(self):
    srv = ServerModel(
        name="Custom Offset Server",
        server_id="srv_custom",
        app_id="896660",
        query_port_offset=5,
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_server_allocation.return_value = ("192.168.1.50", 2456)
    self.countdown.is_running.return_value = False
    self.countdown.get_target.return_value = 0.0
    self.countdown.get_remaining.return_value = 0
    self.a2s.get_player_count.return_value = (2, 8)
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertEqual(server_data["port"], 2456)
    # Custom offset 5 overrides default Valheim offset 1 -> 2456 + 5 = 2461
    self.assertEqual(server_data["query_port"], 2461)
    self.a2s.get_player_count.assert_called_with("1.2.3.4", 2461)

  async def test_status_service_falls_back_to_port_offset_map_when_offset_is_zero(self):
    srv = ServerModel(
        name="Valheim Zero Offset",
        server_id="srv_valheim_zero",
        app_id="896660",
        query_port_offset=0,
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_server_allocation.return_value = ("192.168.1.50", 2456)
    self.countdown.is_running.return_value = False
    self.countdown.get_target.return_value = 0.0
    self.countdown.get_remaining.return_value = 0
    self.a2s.get_player_count.return_value = (3, 10)
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertEqual(server_data["port"], 2456)
    # Valheim offset in PORT_OFFSET_MAP is 1 -> 2456 + 1 = 2457
    self.assertEqual(server_data["query_port"], 2457)
    self.a2s.get_player_count.assert_called_with("1.2.3.4", 2457)

  async def test_status_service_unmapped_app_zero_offset_returns_game_port(self):
    srv = ServerModel(
        name="Palworld Zero Offset",
        server_id="srv_pal_zero",
        app_id="2394010",
        query_port_offset=0,
    )
    cfg = AppConfigModel(
        panel_url="http://panel.example.com",
        api_key="ptlc_key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_server_allocation.return_value = ("192.168.1.50", 8211)
    self.countdown.is_running.return_value = False
    self.countdown.get_target.return_value = 0.0
    self.countdown.get_remaining.return_value = 0
    self.a2s.get_player_count.return_value = (5, 32)
    self.preview_store.get_preview.return_value = None

    snapshot = await self.service.get_status_snapshot()
    server_data = snapshot["servers"][0]
    self.assertEqual(server_data["port"], 8211)
    # Palworld has no entry in PORT_OFFSET_MAP -> port 8211
    self.assertEqual(server_data["query_port"], 8211)

  async def test_explicit_power_tracker_injection(self):
    mock_tracker = MagicMock()
    mock_tracker.get_valid_cache.return_value = PowerState.STARTING
    service = StatusAggregationService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        preview_store=self.preview_store,
        power_tracker=mock_tracker,
    )
    self.assertIs(service.power_tracker, mock_tracker)

    srv = ServerModel(name="Enshrouded", server_id="srv-1", app_id="2278520")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[srv])
    self.countdown.is_running.return_value = False

    status = await service.get_single_server_status(cfg, "1.2.3.4", 0, srv)
    self.assertIsNotNone(status)
    self.assertEqual(status.power_state, PowerState.STARTING)
    mock_tracker.get_valid_cache.assert_called_with("srv-1")
    self.ptero.get_power_state.assert_not_called()

  async def test_status_aggregation_service_without_power_tracker(self):
    service = StatusAggregationService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        preview_store=self.preview_store,
        power_tracker=None,
    )
    self.assertIsNone(service.power_tracker)
    srv = ServerModel(name="Enshrouded", server_id="srv-1", app_id="2278520")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[srv])
    self.ptero.get_power_state.return_value = "running"
    self.countdown.is_running.return_value = False

    status = await service.get_single_server_status(cfg, "1.2.3.4", 0, srv)
    self.assertIsNotNone(status)
    self.assertEqual(status.power_state, PowerState.RUNNING)
    self.ptero.get_power_state.assert_called_once()


class TestResolveQueryPort(unittest.TestCase):

  def test_resolve_query_port_with_nonzero_offset_direct_override(self):
    # Non-zero offset overrides mapped games
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=2), 2458)
    self.assertEqual(resolve_query_port("896660", 2456, query_port_offset=10), 2466)
    # Non-zero offset for unmapped games
    self.assertEqual(resolve_query_port(999999, 7777, query_port_offset=3), 7780)
    self.assertEqual(resolve_query_port("unknown_game", 8000, query_port_offset=5), 8005)

  def test_resolve_query_port_with_negative_offset(self):
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=-1), 2455)
    self.assertEqual(resolve_query_port("custom", 10000, query_port_offset=-50), 9950)

  def test_resolve_query_port_zero_offset_falls_back_to_port_offset_map(self):
    # Valheim
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset=0), 2457)
    self.assertEqual(resolve_query_port("896660", 2456), 2457)
    # Enshrouded
    self.assertEqual(resolve_query_port(2278520, 15636, query_port_offset=0), 15637)
    # V Rising
    self.assertEqual(resolve_query_port(1829350, 9876, query_port_offset=0), 9877)
    # 7 Days to Die
    self.assertEqual(resolve_query_port(294420, 26900, query_port_offset=0), 26901)

  def test_resolve_query_port_zero_offset_unmapped_returns_game_port(self):
    self.assertEqual(resolve_query_port(2394010, 8211, query_port_offset=0), 8211)
    self.assertEqual(resolve_query_port(999999, 7777, query_port_offset=0), 7777)
    self.assertEqual(resolve_query_port("invalid_appid", 7777, query_port_offset=0), 7777)

  def test_resolve_query_port_falsy_game_port(self):
    self.assertEqual(resolve_query_port(896660, 0, query_port_offset=1), 0)
    self.assertEqual(resolve_query_port(896660, None, query_port_offset=1), 0)

  def test_resolve_query_port_string_offset(self):
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset="3"), 2459)
    # Invalid string offset falls back to 0 -> fallback to PORT_OFFSET_MAP (Valheim +1)
    self.assertEqual(resolve_query_port(896660, 2456, query_port_offset="invalid"), 2457)

  def test_resolve_query_port_string_game_port(self):
    self.assertEqual(resolve_query_port(896660, "2456", query_port_offset=2), 2458)
    self.assertEqual(resolve_query_port(896660, "2456", query_port_offset=0), 2457)
    self.assertEqual(resolve_query_port(896660, " 2456 ", query_port_offset=" 3 "), 2459)
    self.assertEqual(resolve_query_port(896660, "0", query_port_offset=1), 0)
    self.assertEqual(resolve_query_port(896660, "", query_port_offset=1), 0)
    self.assertEqual(resolve_query_port(896660, "invalid_port", query_port_offset=1), 0)

  def test_resolve_query_port_out_of_range_clamping(self):
    # Port must be within 1..65535; out-of-range offsets should return 0
    self.assertEqual(resolve_query_port(896660, 65530, query_port_offset=10), 0)
    self.assertEqual(resolve_query_port(896660, 1000, query_port_offset=-2000), 0)

  def test_resolve_query_port_importable_from_status_service(self):
    from app.services.status_service import resolve_query_port as status_resolve
    self.assertEqual(status_resolve(896660, 2456, query_port_offset=4), 2460)


if __name__ == "__main__":
  unittest.main()

