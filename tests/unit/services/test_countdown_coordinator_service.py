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

  def test_cancel_countdown_by_server_id(self):
    self.countdown.start("srv-10", 300)
    self.restarted_builds["srv-10"] = "build-abc"

    self.coordinator.cancel_countdown("srv-10", reason="Server deleted")

    self.assertFalse(self.countdown.is_running("srv-10"))
    self.assertNotIn("srv-10", self.restarted_builds)
    st = self.runtime_state.get_server_state("srv-10")
    self.assertIn("Server deleted", st.last_status)

  def test_cancel_countdown_empty_or_whitespace_noop(self):
    self.coordinator.cancel_countdown("")
    self.coordinator.cancel_countdown("   ")
    self.assertEqual(len(self.runtime_state.get_all_server_states()), 0)

  def test_cancel_countdown_idle_server_leaves_runtime_state_untouched(self):
    self.coordinator.cancel_countdown("srv-idle", reason="Manual restart")
    self.assertEqual(len(self.runtime_state.get_all_server_states()), 0)

  def test_cancel_all_countdowns(self):
    self.countdown.start("srv-a", 300)
    self.countdown.start("srv-b", 300)
    self.restarted_builds["srv-a"] = "build-1"
    self.restarted_builds["srv-b"] = "build-2"

    tasks = self.coordinator.cancel_all_countdowns(reason="Application shutdown")

    self.assertFalse(self.countdown.is_running("srv-a"))
    self.assertFalse(self.countdown.is_running("srv-b"))
    self.assertEqual(len(self.restarted_builds), 0)
    self.assertIsInstance(tasks, list)

  async def test_countdown_manager_stop_all_cancels_active_tasks(self):
    cancelled_tasks = []

    async def dummy_task(name):
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        cancelled_tasks.append(name)
        raise

    task_a = asyncio.create_task(dummy_task("task_a"))
    task_b = asyncio.create_task(dummy_task("task_b"))
    await asyncio.sleep(0)  # Allow tasks to begin execution and enter sleep

    self.countdown.start("srv-a", 300, task=task_a)
    self.countdown.start("srv-b", 300, task=task_b)

    self.countdown.stop_all()

    # Yield control so cancellations propagate
    await asyncio.sleep(0.01)

    self.assertTrue(task_a.cancelled() or task_a.done())
    self.assertTrue(task_b.cancelled() or task_b.done())
    self.assertIn("task_a", cancelled_tasks)
    self.assertIn("task_b", cancelled_tasks)
    self.assertFalse(self.countdown.is_running("srv-a"))
    self.assertFalse(self.countdown.is_running("srv-b"))

  async def test_cancel_all_countdowns_returns_cancelled_tasks(self):
    async def dummy():
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    t1 = asyncio.create_task(dummy())
    t2 = asyncio.create_task(dummy())
    await asyncio.sleep(0)

    self.countdown.start("srv-1", 300, task=t1)
    self.countdown.start("srv-2", 300, task=t2)

    tasks = self.coordinator.cancel_all_countdowns()
    self.assertEqual(len(tasks), 2)
    await asyncio.sleep(0.01)
    self.assertTrue(t1.cancelled() or t1.done())
    self.assertTrue(t2.cancelled() or t2.done())

  def test_countdown_manager_active_server_ids_and_target_only_stop_all(self):
    self.countdown.start("srv-target-only", 300)
    self.assertIn("srv-target-only", self.countdown.active_server_ids())
    self.assertTrue(self.countdown.is_running("srv-target-only"))

    self.countdown.stop_all()

    self.assertFalse(self.countdown.is_running("srv-target-only"))
    self.assertEqual(len(self.countdown.active_server_ids()), 0)


