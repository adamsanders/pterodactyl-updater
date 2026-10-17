import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.models import (
    AppConfigModel,
    LocalBuildResult,
    PowerState,
    ServerModel,
    ServerNameResult,
    ServerUpdateStatus,
)
from app.services.countdown import CountdownManager
from app.services.countdown_coordinator_service import CountdownCoordinatorService
from app.services.runtime_state import RuntimeStateStore
from app.services.server_inspection_service import ServerInspectionService


class TestServerInspectionService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.countdown = CountdownManager()
    self.announcements = MagicMock()
    self.runtime_state = RuntimeStateStore()
    self.restarted_builds = {}

    self.ptero.get_local_build.return_value = LocalBuildResult(build_id="100")
    self.ptero.get_server_name.return_value = ServerNameResult(name="Test Server")
    self.steam.get_latest_build.return_value = "100"

    self.coordinator = CountdownCoordinatorService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        announcements=self.announcements,
        runtime_state=self.runtime_state,
        restarted_builds=self.restarted_builds,
    )

    self.service = ServerInspectionService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        countdown_coordinator=self.coordinator,
        countdown=self.countdown,
        runtime_state=self.runtime_state,
        restarted_builds=self.restarted_builds,
    )

  async def test_evaluate_build_status_up_to_date(self):
    server = ServerModel(
        name="Valheim",
        server_id="srv-1",
        app_id="896660",
        current_build="100",
        latest_build="100",
    )
    self.countdown.start("srv-1", 300)
    self.restarted_builds["srv-1"] = "100"

    await self.service.evaluate_build_status(
        server=server,
        latest_build="100",
        local_build="100",
        read_error=None,
        power_state=PowerState.RUNNING,
    )

    self.assertFalse(self.countdown.is_running("srv-1"))
    self.assertNotIn("srv-1", self.restarted_builds)
    st = self.runtime_state.get_server_state("srv-1")
    self.assertEqual(st.last_status, ServerUpdateStatus.UP_TO_DATE)

  async def test_evaluate_build_status_read_error(self):
    server = ServerModel(name="Valheim", server_id="srv-1", app_id="896660")
    await self.service.evaluate_build_status(
        server=server,
        latest_build="200",
        local_build=None,
        read_error="Manifest missing",
        power_state=PowerState.RUNNING,
    )
    self.assertEqual(
        self.runtime_state.get_server_state("srv-1").last_status,
        "Error: Manifest missing",
    )

  async def test_evaluate_build_status_unreachable_steam(self):
    server = ServerModel(name="Valheim", server_id="srv-1", app_id="896660")
    await self.service.evaluate_build_status(
        server=server,
        latest_build=None,
        local_build="100",
        read_error=None,
        power_state=PowerState.RUNNING,
    )
    self.assertIn(
        "Unreachable SteamCMD API",
        self.runtime_state.get_server_state("srv-1").last_status,
    )

  async def test_evaluate_build_status_triggers_countdown_when_running_and_auto_restart(self):
    server = ServerModel(
        name="Valheim",
        server_id="srv-1",
        app_id="896660",
        auto_restart=True,
    )
    self.coordinator.start_countdown = MagicMock()

    await self.service.evaluate_build_status(
        server=server,
        latest_build="200",
        local_build="100",
        read_error=None,
        power_state=PowerState.RUNNING,
    )

    self.assertEqual(
        self.runtime_state.get_server_state("srv-1").last_status,
        ServerUpdateStatus.COUNTDOWN_ACTIVE,
    )
    self.coordinator.start_countdown.assert_called_once_with(server)

  async def test_evaluate_build_status_offline_does_not_trigger_countdown(self):
    server = ServerModel(
        name="Valheim",
        server_id="srv-1",
        app_id="896660",
        auto_restart=True,
    )
    self.coordinator.start_countdown = MagicMock()

    await self.service.evaluate_build_status(
        server=server,
        latest_build="200",
        local_build="100",
        read_error=None,
        power_state=PowerState.OFFLINE,
    )

    self.assertEqual(
        self.runtime_state.get_server_state("srv-1").last_status,
        ServerUpdateStatus.UPDATE_AVAILABLE,
    )
    self.coordinator.start_countdown.assert_not_called()

  async def test_inspect_server_synchronizes_name_change(self):
    server = ServerModel(
        name="Old Name",
        server_id="srv-1",
        app_id="896660",
        manifest_path="manifest.acf",
    )
    cfg = AppConfigModel(servers=[server])
    self.repo.load.return_value = cfg
    self.ptero.get_server_name.return_value = ServerNameResult(name="New Synced Name")
    self.ptero.get_power_state.return_value = "running"
    self.ptero.get_local_build.return_value = LocalBuildResult(build_id="100")
    self.steam.get_latest_build.return_value = "100"

    cache = {}
    await self.service.inspect_server(
        server=server,
        panel_url="http://panel.test",
        api_key="key",
        steam_build_cache=cache,
    )

    self.assertEqual(server.name, "New Synced Name")
    self.repo.save.assert_called()
    self.assertEqual(cache.get("896660"), "100")

  async def test_inspect_server_aborts_countdown_on_external_stop(self):
    server = ServerModel(
        name="Valheim",
        server_id="srv-1",
        app_id="896660",
        manifest_path="manifest.acf",
    )
    self.countdown.start("srv-1", 300)
    self.restarted_builds["srv-1"] = "999"
    self.ptero.get_server_name.return_value = ServerNameResult(name="Valheim")
    self.ptero.get_power_state.return_value = "stopping"

    await self.service.inspect_server(
        server=server,
        panel_url="http://panel.test",
        api_key="key",
        steam_build_cache={},
    )

    self.assertFalse(self.countdown.is_running("srv-1"))
    self.assertNotIn("srv-1", self.restarted_builds)
    self.assertIn(
        "Manual stopping detected",
        self.runtime_state.get_server_state("srv-1").last_status,
    )
