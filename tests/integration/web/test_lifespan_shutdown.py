import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from app.core.models import AppConfigModel, ServerModel
from app.main import lifespan


class TestLifespanShutdown(unittest.IsolatedAsyncioTestCase):
  """Validates application lifespan graceful shutdown, countdown cancellation, and loop termination."""

  async def test_lifespan_shutdown_cancels_all_countdowns_and_stops_loop(self):
    mock_repo = MagicMock()
    server1 = ServerModel(name="Valheim 1", server_id="srv-val-1")
    server2 = ServerModel(name="Valheim 2", server_id="srv-val-2")
    mock_repo.load.return_value = AppConfigModel(servers=[server1, server2], ssl_verify=True)

    test_app = FastAPI()

    with patch("app.main.ConfigRepository", return_value=mock_repo), \
         patch("app.main.httpx.AsyncClient") as mock_client_cls:

      mock_client_instance = AsyncMock()
      mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

      async with lifespan(test_app):
        # 1. Verify application state dependencies were registered
        orchestrator = test_app.state.orchestrator
        countdown = test_app.state.countdown
        countdown_coordinator = test_app.state.countdown_coordinator

        self.assertIsNotNone(orchestrator)
        self.assertIsNotNone(countdown)
        self.assertIsNotNone(countdown_coordinator)

        # 2. Verify orchestrator loop was started
        self.assertIsNotNone(orchestrator._loop_task)
        self.assertFalse(orchestrator._loop_task.done())
        self.assertTrue(orchestrator._running)

        # 3. Simulate active in-progress countdown tasks
        async def dummy_countdown():
          try:
            await asyncio.sleep(100)
          except asyncio.CancelledError:
            pass

        task1 = asyncio.create_task(dummy_countdown())
        task2 = asyncio.create_task(dummy_countdown())

        countdown.start("srv-val-1", 900, task=task1)
        countdown.start("srv-val-2", 900, task=task2)
        countdown_coordinator.record_restarted_build("srv-val-1", "b100")
        countdown_coordinator.record_restarted_build("srv-val-2", "b200")

        self.assertTrue(countdown.is_running("srv-val-1"))
        self.assertTrue(countdown.is_running("srv-val-2"))

      # 4. Exited lifespan context manager (shutdown complete)
      # Verify orchestrator background loop was cancelled and stopped
      self.assertFalse(orchestrator._running)
      self.assertTrue(orchestrator._loop_task.done())

      # Verify countdown tasks across all servers were cancelled
      self.assertTrue(task1.done())
      self.assertTrue(task2.done())
      self.assertFalse(countdown.is_running("srv-val-1"))
      self.assertFalse(countdown.is_running("srv-val-2"))
      self.assertFalse(countdown_coordinator.has_restarted_build("srv-val-1", "b100"))
      self.assertFalse(countdown_coordinator.has_restarted_build("srv-val-2", "b200"))


if __name__ == "__main__":
  unittest.main()
