import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.models import AppConfigModel, ServerModel
from app.services.countdown import CountdownManager
from app.services.countdown_coordinator_service import CountdownCoordinatorService
from app.services.runtime_state import RuntimeStateStore


class TestCountdownCoordinatorService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.countdown = CountdownManager()
    self.announcements = AsyncMock()
    self.runtime_state = RuntimeStateStore()
    self.restarted_builds = {}

    self.coordinator = CountdownCoordinatorService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        announcements=self.announcements,
        runtime_state=self.runtime_state,
        restarted_builds=self.restarted_builds,
    )

  def test_restarted_builds_tracking_methods(self):
    self.coordinator.record_restarted_build("srv-1", "build-100")
    self.assertTrue(self.coordinator.has_restarted_build("srv-1", "build-100"))
    self.assertFalse(self.coordinator.has_restarted_build("srv-1", "build-200"))
    self.assertEqual(self.coordinator.get_restarted_build("srv-1"), "build-100")

    self.coordinator.clear_restarted_build("srv-1")
    self.assertFalse(self.coordinator.has_restarted_build("srv-1", "build-100"))

    self.coordinator.record_restarted_build("srv-2", "build-200")
    self.coordinator.record_restarted_build("srv-3", "build-300")
    self.coordinator.clear_restarted_build()  # Clear all
    self.assertEqual(len(self.restarted_builds), 0)

  def test_cancel_active_countdown(self):
    server = ServerModel(name="Valheim", server_id="srv-1")
    self.countdown.start("srv-1", 300)
    self.restarted_builds["srv-1"] = "build-100"

    self.coordinator.cancel_active_countdown(server, reason="Manual restart")

    self.assertFalse(self.countdown.is_running("srv-1"))
    self.assertNotIn("srv-1", self.restarted_builds)
    st = self.runtime_state.get_server_state("srv-1")
    self.assertIn("Manual restart", st.last_status)

  async def test_start_countdown_attaches_task(self):
    server = ServerModel(name="Valheim", server_id="srv-1", latest_build="500")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key")
    self.repo.load.return_value = cfg

    with patch("asyncio.sleep", new_callable=AsyncMock):
      task = self.coordinator.start_countdown(server)
      self.assertTrue(self.countdown.is_running("srv-1"))
      await task
      self.assertFalse(self.countdown.is_running("srv-1"))

  async def test_delayed_restart_routine_complete_execution(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
    )
    self.repo.load.return_value = cfg
    server = ServerModel(
        name="Valheim Server",
        server_id="srv-123",
        current_build="100",
        latest_build="200",
        auto_restart=True,
    )

    sleeps = []

    async def fake_sleep(secs):
      sleeps.append(secs)

    with patch("asyncio.sleep", side_effect=fake_sleep):
      await self.coordinator.delayed_restart_routine(server)

    self.assertEqual(sleeps, [300, 300, 240, 60])
    self.ptero.trigger_restart.assert_called_once_with(
        "http://panel.test", "key", "srv-123"
    )
    self.assertEqual(self.coordinator.get_restarted_build("srv-123"), "200")
    self.assertFalse(self.countdown.is_running("srv-123"))

  async def test_delayed_restart_routine_cancellation_cleans_up(self):
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="key")
    self.repo.load.return_value = cfg
    server = ServerModel(name="Valheim", server_id="srv-1")

    async def cancel_on_sleep(secs):
      raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=cancel_on_sleep):
      with self.assertRaises(asyncio.CancelledError):
        await self.coordinator.delayed_restart_routine(server)

    self.assertFalse(self.countdown.is_running("srv-1"))
