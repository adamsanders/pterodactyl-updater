import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.models import AppConfigModel, ServerModel
from app.services.countdown import CountdownManager
from app.services.preview_store import WebhookPreviewStore
from app.services.updater import UpdateOrchestrator
from app.adapters.pterodactyl import PterodactylAdapter


class TestCountdownManager(unittest.IsolatedAsyncioTestCase):

  def test_countdown_basic_lifecycle(self):
    cm = CountdownManager()
    self.assertFalse(cm.is_running("srv1"))
    self.assertEqual(cm.get_remaining("srv1"), 0)

    cm.start("srv1", duration_seconds=10)
    self.assertTrue(cm.is_running("srv1"))
    self.assertGreater(cm.get_remaining("srv1"), 0)
    self.assertGreater(cm.get_target("srv1"), time.time())

    cm.stop("srv1")
    self.assertFalse(cm.is_running("srv1"))
    self.assertEqual(cm.get_remaining("srv1"), 0)

  async def test_countdown_active_task_keeps_is_running_true(self):
    cm = CountdownManager()

    # Target is set in the past, but an active task is attached
    async def dummy_work():
      await asyncio.sleep(0.5)

    task = asyncio.create_task(dummy_work())
    cm.start("srv1", duration_seconds=-1, task=task)

    # Even though timestamp expired, the task is still running
    self.assertTrue(cm.is_running("srv1"))

    # When task finishes
    await task
    self.assertFalse(cm.is_running("srv1"))

  async def test_countdown_attach_task_cancels_old_task(self):
    cm = CountdownManager()

    async def long_work():
      try:
        await asyncio.sleep(10)
      except asyncio.CancelledError:
        pass

    task1 = asyncio.create_task(long_work())
    cm.attach_task("srv1", task1)

    task2 = asyncio.create_task(long_work())
    cm.attach_task("srv1", task2)

    await asyncio.sleep(0.01)
    self.assertTrue(task1.cancelled() or task1.done())
    self.assertFalse(task2.done())

    cm.stop("srv1")
    await asyncio.sleep(0.01)
    self.assertTrue(task2.cancelled() or task2.done())


class TestPterodactylAdapterRestart(unittest.IsolatedAsyncioTestCase):

  async def test_trigger_restart_online(self):
    client = MagicMock()
    adapter = PterodactylAdapter(client=client)
    adapter.get_power_state = AsyncMock(return_value="running")
    adapter.send_power_signal = AsyncMock(return_value=(True, None))

    success, err = await adapter.trigger_restart("http://panel", "key", "srv1")
    self.assertTrue(success)
    adapter.send_power_signal.assert_called_once_with(
        "http://panel", "key", "srv1", "restart"
    )

  async def test_trigger_restart_offline(self):
    client = MagicMock()
    adapter = PterodactylAdapter(client=client)
    adapter.get_power_state = AsyncMock(return_value="offline")
    adapter.send_power_signal = AsyncMock(return_value=(True, None))

    success, err = await adapter.trigger_restart("http://panel", "key", "srv1")
    self.assertTrue(success)
    adapter.send_power_signal.assert_called_once_with(
        "http://panel", "key", "srv1", "start"
    )

  async def test_trigger_restart_fallback_on_restart_failure(self):
    client = MagicMock()
    adapter = PterodactylAdapter(client=client)
    adapter.get_power_state = AsyncMock(return_value="running")
    # First restart fails, fallback start succeeds
    adapter.send_power_signal = AsyncMock(
        side_effect=[(False, "HTTP 400"), (True, None)]
    )

    success, err = await adapter.trigger_restart("http://panel", "key", "srv1")
    self.assertTrue(success)
    self.assertEqual(adapter.send_power_signal.call_count, 2)
    adapter.send_power_signal.assert_any_call(
        "http://panel", "key", "srv1", "restart"
    )
    adapter.send_power_signal.assert_any_call(
        "http://panel", "key", "srv1", "start"
    )

  async def test_execute_graceful_restart_delegates_to_trigger_restart(self):
    client = MagicMock()
    adapter = PterodactylAdapter(client=client)
    adapter.trigger_restart = AsyncMock(return_value=(True, None))

    await adapter.execute_graceful_restart("http://panel", "key", "srv1")
    adapter.trigger_restart.assert_called_once_with("http://panel", "key", "srv1")


class TestUpdateOrchestratorRestart(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.discord = AsyncMock()
    self.preview_store = WebhookPreviewStore()
    self.countdown = CountdownManager()
    self.orchestrator = UpdateOrchestrator(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        discord=self.discord,
        preview_store=self.preview_store,
        countdown=self.countdown,
    )

  async def test_delayed_restart_routine_schedule_and_api_restart(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        discord_webhook="https://discord.com/webhook",
        test_mode=False,
    )
    self.repo.load.return_value = cfg
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        current_build="100",
        latest_build="200",
        auto_restart=True,
    )

    slept_durations = []

    async def fake_sleep(seconds):
      slept_durations.append(seconds)

    with patch("asyncio.sleep", side_effect=fake_sleep):
      await self.orchestrator.delayed_restart_routine(server)

    # Total sleep time across the 15, 10, 5, 1 min countdown intervals must sum to exactly 900 seconds (15 minutes)
    self.assertEqual(slept_durations, [300, 300, 240, 60])
    self.assertEqual(sum(slept_durations), 900)

    # Server status must indicate restart
    self.assertEqual(server.last_status, "Restarting server via Pterodactyl API...")

    # Pterodactyl API trigger_restart must be called with the server credentials
    self.ptero.trigger_restart.assert_called_once_with(
        "http://panel.test", "key", "srv123"
    )

    # Countdown must be stopped
    self.assertFalse(self.countdown.is_running("srv123"))

    # The latest build must be recorded in _restarted_builds
    self.assertEqual(self.orchestrator._restarted_builds.get("srv123"), "200")

  async def test_does_not_restart_countdown_if_already_restarted_for_build(self):
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        current_build="100",
        latest_build="200",
        auto_restart=True,
    )
    # Simulate that server was already restarted for build 200
    self.orchestrator._restarted_builds["srv123"] = "200"

    await self.orchestrator._evaluate_build_status(
        server=server,
        latest_build="200",
        local_build="100",
        read_error=None,
        power_state="running",
    )

    # Should NOT start countdown
    self.assertFalse(self.countdown.is_running("srv123"))
    self.assertEqual(
        server.last_status, "Restart dispatched — waiting for build update"
    )

  async def test_does_not_start_countdown_if_server_is_offline(self):
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        current_build="100",
        latest_build="200",
        auto_restart=True,
    )

    await self.orchestrator._evaluate_build_status(
        server=server,
        latest_build="200",
        local_build="100",
        read_error=None,
        power_state="offline",
    )

    # Offline servers must NOT start a countdown
    self.assertFalse(self.countdown.is_running("srv123"))
    self.assertEqual(server.last_status, "Update Available")

  async def test_clears_restarted_build_when_server_becomes_up_to_date(self):
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        current_build="200",
        latest_build="200",
        auto_restart=True,
    )
    self.orchestrator._restarted_builds["srv123"] = "200"

    await self.orchestrator._evaluate_build_status(
        server=server,
        latest_build="200",
        local_build="200",
        read_error=None,
        power_state="running",
    )

    self.assertNotIn("srv123", self.orchestrator._restarted_builds)
    self.assertEqual(server.last_status, "Up to date")

  async def test_broadcast_warning_patchnotes_only_on_first_warning(self):
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        discord_webhook="https://discord.com/webhook",
        test_mode=False,
    )
    self.repo.load.return_value = cfg
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        app_id="896660",
        discord_alerts=True,
        warn_discord_countdown=True,
    )
    self.steam.fetch_patchnotes.return_value = {"title": "Update Notes"}

    # Warning at 15 mins (include_patchnotes=True)
    await self.orchestrator.broadcast_warning(server, minutes_left=15, include_patchnotes=True)
    self.steam.fetch_patchnotes.assert_called_once_with("896660")
    self.discord.send_notification.assert_called_with(
        webhook_url="https://discord.com/webhook",
        message="⚠️ **[Test Game Server]** Server will restart in 15 minute(s) for an update. Please find a safe spot!",
        embed={"title": "Update Notes"},
    )

    # Warning at 10 mins (include_patchnotes=False)
    self.steam.fetch_patchnotes.reset_mock()
    await self.orchestrator.broadcast_warning(server, minutes_left=10, include_patchnotes=False)
    self.steam.fetch_patchnotes.assert_not_called()
    self.discord.send_notification.assert_called_with(
        webhook_url="https://discord.com/webhook",
        message="⚠️ **[Test Game Server]** Server will restart in 10 minute(s) for an update. Please find a safe spot!",
        embed=None,
    )

  async def test_inspect_server_skips_manifest_when_offline_following_restart(self):
    server = ServerModel(
        name="Test Game Server",
        server_id="srv123",
        current_build="100",
        latest_build="200",
    )
    self.orchestrator._restarted_builds["srv123"] = "200"
    self.ptero.get_server_name.return_value = ("Test Game Server", None)
    self.ptero.get_power_state.return_value = "offline"
    self.steam.get_latest_build.return_value = "200"

    await self.orchestrator._inspect_server(
        server=server,
        panel_url="http://panel.test",
        api_key="key",
        steam_build_cache={},
    )

    # Should skip get_local_build because server is offline following update restart
    self.ptero.get_local_build.assert_not_called()


if __name__ == "__main__":
  unittest.main()
