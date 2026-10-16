import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.adapters.power_tracker import PowerStateTracker
from app.core.models import (
    AppConfigModel,
    OperationResult,
    PlayerMetrics,
    PowerState,
    ServerAllocation,
    ServerModel,
    ServerStatusDTO,
    SingleServerSaveRequest,
)
from app.services.announcement_service import AnnouncementService
from app.services.countdown import CountdownManager
from app.services.preview_store import WebhookPreviewStore
from app.services.runtime_state import RuntimeStateStore
from app.services.server_config_service import ServerConfigService
from app.services.server_power_service import ServerPowerService
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.web.schemas import SettingsFormData
from starlette.datastructures import FormData


class TestConfigurableBroadcastSyntax(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.service = AnnouncementService(
        repository=self.repo,
        ptero=self.ptero,
    )

  async def test_broadcast_warning_uses_default_say_command(self):
    server = ServerModel(name="Valheim", server_id="srv-1")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[server])
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(server, 15)

    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "key",
        "srv-1",
        "say Server will restart in 15 minute(s) for an update. Please find a safe spot!",
    )

  async def test_broadcast_warning_uses_custom_palworld_broadcast(self):
    server = ServerModel(
        name="Palworld",
        server_id="srv-pal",
        warn_ingame_countdown=True,
        broadcast_command_template="broadcast {message}",
    )
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[server])
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(server, 10)

    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "key",
        "srv-pal",
        "broadcast Server will restart in 10 minute(s) for an update. Please find a safe spot!",
    )

  async def test_broadcast_warning_uses_custom_project_zomboid_servermsg(self):
    server = ServerModel(
        name="Project Zomboid",
        server_id="srv-pz",
        warn_ingame_countdown=True,
        broadcast_command_template='servermsg "{message}"',
    )
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[server])
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(server, 5)

    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "key",
        "srv-pz",
        'servermsg "Server will restart in 5 minute(s) for an update. Please find a safe spot!"',
    )

  async def test_broadcast_warning_falls_back_on_invalid_format_string(self):
    server = ServerModel(
        name="Broken Template",
        server_id="srv-bad",
        warn_ingame_countdown=True,
        broadcast_command_template="bad {invalid_key}",
    )
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[server])
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(server, 1)

    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "key",
        "srv-bad",
        "say Server will restart in 1 minute(s) for an update. Please find a safe spot!",
    )

  async def test_broadcast_warning_supports_command_prefix_without_placeholder(self):
    server = ServerModel(
        name="Palworld",
        server_id="srv-pal",
        warn_ingame_countdown=True,
        broadcast_command_template="broadcast",
    )
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[server])
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(server, 10)

    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "key",
        "srv-pal",
        "broadcast Server will restart in 10 minute(s) for an update. Please find a safe spot!",
    )

  async def test_settings_form_data_extracts_broadcast_command_template(self):
    form = FormData({
        "panel_url": "http://panel.test",
        "api_key": "key",
        "check_interval": "15",
        "srv_name_0": "Palworld",
        "srv_id_0": "srv-pal",
        "srv_appid_0": "2394010",
        "srv_manifest_0": "manifest.acf",
        "srv_port_offset_0": "0",
        "srv_broadcast_cmd_0": "broadcast {message}",
    })
    current_servers = [ServerModel(server_id="srv-pal", name="Palworld")]
    dto = await SettingsFormData.from_form(form, current_servers)

    self.assertEqual(len(dto.servers), 1)
    self.assertEqual(dto.servers[0].broadcast_command_template, "broadcast {message}")


class TestStatusAggregationServiceTelemetryCaching(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.countdown = CountdownManager()
    self.preview_store = WebhookPreviewStore()
    self.a2s = AsyncMock()
    self.runtime_state = RuntimeStateStore()

    self.service = StatusAggregationService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        preview_store=self.preview_store,
        a2s=self.a2s,
        runtime_state=self.runtime_state,
        telemetry_cache_ttl=5.0,
    )

  async def test_telemetry_cache_suppresses_rapid_successive_queries(self):
    srv = ServerModel(name="Valheim", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[srv])
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_server_allocation.return_value = ServerAllocation("10.0.0.1", 2456)
    self.a2s.get_player_count.return_value = PlayerMetrics(3, 10)

    # First poll: cache is empty, calls ptero and a2s
    snap1 = await self.service.get_status_snapshot()
    self.assertEqual(self.ptero.get_power_state.call_count, 1)
    self.assertEqual(self.ptero.get_server_allocation.call_count, 1)
    self.assertEqual(self.a2s.get_player_count.call_count, 1)
    self.assertEqual(snap1["servers"][0]["power_state"], "running")
    self.assertEqual(snap1["servers"][0]["player_count"], 3)

    # Second poll immediately after (within 5s TTL): uses short-TTL cached telemetry
    snap2 = await self.service.get_status_snapshot()
    # Call counts MUST NOT increase
    self.assertEqual(self.ptero.get_power_state.call_count, 1)
    self.assertEqual(self.ptero.get_server_allocation.call_count, 1)
    self.assertEqual(self.a2s.get_player_count.call_count, 1)
    self.assertEqual(snap2["servers"][0]["player_count"], 3)

    # Cache invalidation forces fresh queries
    self.service.invalidate_cache("srv-1")
    snap3 = await self.service.get_status_snapshot()
    self.assertEqual(self.ptero.get_power_state.call_count, 2)
    self.assertEqual(self.ptero.get_server_allocation.call_count, 2)
    self.assertEqual(self.a2s.get_player_count.call_count, 2)

  async def test_telemetry_cache_reflects_real_time_power_tracker_state(self):
    srv = ServerModel(name="Valheim", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[srv])
    self.repo.load.return_value = cfg
    self.ptero.get_external_ip.return_value = "1.2.3.4"
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_server_allocation.return_value = ServerAllocation("10.0.0.1", 2456)
    self.a2s.get_player_count.return_value = PlayerMetrics(5, 20)

    # Wire power tracker
    tracker = PowerStateTracker()
    self.service.power_tracker = tracker

    # Initial snapshot: running with 5 players
    snap1 = await self.service.get_status_snapshot()
    self.assertEqual(snap1["servers"][0]["power_state"], "running")
    self.assertEqual(snap1["servers"][0]["player_count"], 5)

    # Power signal sent externally (registered in tracker as STARTING)
    tracker.register_signal("srv-1", "start")

    # Immediate snapshot poll within TTL: must instantly reflect STARTING and clear player count
    snap2 = await self.service.get_status_snapshot()
    self.assertEqual(snap2["servers"][0]["power_state"], "starting")
    self.assertIsNone(snap2["servers"][0]["player_count"])


class TestServiceDecompositionEdgeCases(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.countdown = CountdownManager()
    self.runtime_state = RuntimeStateStore()

  async def test_save_single_server_can_clear_manifest_and_appid(self):
    srv = ServerModel(
        name="Custom Valheim",
        server_id="srv-1",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
    )
    cfg = AppConfigModel(servers=[srv])
    self.repo.load.return_value = cfg

    config_service = ServerConfigService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        runtime_state=self.runtime_state,
    )

    # Request explicitly setting manifest_path to empty string
    req = SingleServerSaveRequest(
        name="Custom Valheim",
        server_id="srv-1",
        manifest_path="",
        app_id="896660",
        broadcast_command_template="say {message}",
    )
    updated = await config_service.save_single_server("srv-1", req)

    self.assertEqual(updated.manifest_path, "")

  async def test_server_service_facade_delegates_power_state_and_graceful_restart(self):
    srv = ServerModel(name="Valheim", server_id="srv-1")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key", servers=[srv])
    self.repo.load.return_value = cfg
    self.ptero.get_power_state.return_value = PowerState.RUNNING
    self.ptero.trigger_restart.return_value = OperationResult(True, None)

    simulator_store = MagicMock()
    orchestrator = MagicMock()

    service = ServerService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        simulator_store=simulator_store,
        countdown=self.countdown,
        orchestrator=orchestrator,
        runtime_state=self.runtime_state,
    )

    state = await service.get_power_state("srv-1")
    self.assertEqual(state, PowerState.RUNNING)

    restart_res = await service.execute_graceful_restart("srv-1")
    self.assertTrue(restart_res.success)
    orchestrator.clear_restarted_build.assert_called_once_with("srv-1")

