import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ConfigurationError, ServerNotFoundError
from app.core.models import (
    AppConfigModel,
    OperationResult,
    PowerSignal,
    PowerState,
    ServerModel,
)
from app.services.countdown import CountdownManager
from app.services.runtime_state import RuntimeStateStore
from app.services.server_power_service import ServerPowerService


class TestServerPowerService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.countdown = CountdownManager()
    self.orchestrator = MagicMock()
    self.runtime_state = RuntimeStateStore()

    self.service = ServerPowerService(
        repository=self.repo,
        ptero=self.ptero,
        countdown=self.countdown,
        orchestrator=self.orchestrator,
        runtime_state=self.runtime_state,
    )

  async def test_send_power_action_invalid_action(self):
    res = await self.service.send_power_action("srv-1", "kaboom")
    self.assertFalse(res.success)
    self.assertEqual(res.status_code, 400)
    self.assertEqual(res.error_type, "InvalidPowerAction")

  async def test_send_power_action_server_not_found(self):
    cfg = AppConfigModel(servers=[])
    self.repo.load.return_value = cfg

    res = await self.service.send_power_action("srv-missing", "start")
    self.assertFalse(res.success)
    self.assertEqual(res.status_code, 404)
    self.assertEqual(res.error_type, "ServerNotFound")

  async def test_send_power_action_incomplete_config(self):
    srv = ServerModel(name="Valheim", server_id="")
    cfg = AppConfigModel(panel_url="", api_key="", servers=[srv])
    self.repo.load.return_value = cfg

    res = await self.service.send_power_action(0, "start")
    self.assertFalse(res.success)
    self.assertEqual(res.status_code, 400)
    self.assertEqual(res.error_type, "ConfigurationError")

  async def test_send_power_action_restart_cancels_countdown_and_clears_orchestrator(self):
    srv = ServerModel(name="Valheim", server_id="srv-1")
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.countdown.start("srv-1", 300)
    self.ptero.send_power_signal.return_value = OperationResult(True, None)

    res = await self.service.send_power_action("srv-1", PowerSignal.RESTART)

    self.assertTrue(res.success)
    self.orchestrator.clear_restarted_build.assert_called_once_with("srv-1")
    self.assertFalse(self.countdown.is_running("srv-1"))
    self.assertIn("restart requested", srv.last_status)
    st = self.runtime_state.get_server_state("srv-1")
    self.assertIn("restart requested", st.last_status)
    self.ptero.send_power_signal.assert_called_once_with(
        panel_url="http://panel.test",
        api_key="key",
        server_id="srv-1",
        signal=PowerSignal.RESTART,
    )

  async def test_get_power_state(self):
    srv = ServerModel(name="Valheim", server_id="srv-1")
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.get_power_state.return_value = PowerState.RUNNING

    state = await self.service.get_power_state("srv-1")
    self.assertEqual(state, PowerState.RUNNING)

  async def test_execute_graceful_restart(self):
    srv = ServerModel(name="Valheim", server_id="srv-1")
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="key",
        servers=[srv],
    )
    self.repo.load.return_value = cfg
    self.ptero.trigger_restart.return_value = OperationResult(True, None)

    res = await self.service.execute_graceful_restart("srv-1")
    self.assertTrue(res.success)
    self.orchestrator.clear_restarted_build.assert_called_once_with("srv-1")
    self.ptero.trigger_restart.assert_called_once_with("http://panel.test", "key", "srv-1")
