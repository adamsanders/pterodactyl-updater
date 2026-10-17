import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
import httpx

from app.composition import (
    ApplicationContainer,
    bind_container_to_app,
    build_container,
    create_announcement_service,
    create_server_service,
    create_status_service,
    create_update_orchestrator,
    shutdown_container,
)
from app.core.models import AppConfigModel
from app.core.protocols import (
    ServerServiceProtocol,
    StatusAggregationGateway,
    UpdateOrchestratorProtocol,
)


class TestCompositionRoot(unittest.IsolatedAsyncioTestCase):
  """Unit tests for the application composition root, container binding, and graceful shutdown."""

  def test_create_status_service_factory_returns_conforming_service(self):
    mock_repo = MagicMock()
    mock_ptero = AsyncMock()
    mock_countdown = MagicMock()
    mock_preview = MagicMock()

    service = create_status_service(
        repository=mock_repo,
        ptero=mock_ptero,
        countdown=mock_countdown,
        preview_store=mock_preview,
    )
    self.assertIsInstance(service, StatusAggregationGateway)

  def test_create_server_service_factory_returns_conforming_service(self):
    mock_repo = MagicMock()
    mock_ptero = AsyncMock()
    mock_steam = AsyncMock()
    mock_simulator = MagicMock()
    mock_countdown = MagicMock()

    service = create_server_service(
        repository=mock_repo,
        ptero=mock_ptero,
        steam=mock_steam,
        simulator_store=mock_simulator,
        countdown=mock_countdown,
    )
    self.assertIsInstance(service, ServerServiceProtocol)

  def test_build_container_assembles_all_gateways_and_services(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_tracker = MagicMock()

    container = build_container(
        repo=mock_repo,
        http_client=mock_client,
        call_tracker=mock_tracker,
    )

    self.assertIsInstance(container, ApplicationContainer)
    self.assertIsNotNone(container.repo)
    self.assertIsNotNone(container.runtime_state)
    self.assertIsNotNone(container.power_tracker)
    self.assertIsNotNone(container.ptero)
    self.assertIsNotNone(container.steam)
    self.assertIsNotNone(container.discord)
    self.assertIsNotNone(container.a2s)
    self.assertIsNotNone(container.countdown)
    self.assertIsNotNone(container.preview_store)
    self.assertIsNotNone(container.simulator_store)
    self.assertIsNotNone(container.announcements)
    self.assertIsNotNone(container.orchestrator)
    self.assertIsNotNone(container.server_service)
    self.assertIsNotNone(container.status_service)
    self.assertIsInstance(container.server_service, ServerServiceProtocol)
    self.assertIsInstance(container.status_service, StatusAggregationGateway)
    self.assertIsInstance(container.orchestrator, UpdateOrchestratorProtocol)
    self.assertIsNotNone(container.server_config_service)
    self.assertIsNotNone(container.server_power_service)
    self.assertIsNotNone(container.inspection_service)
    self.assertIsNotNone(container.countdown_coordinator)

  def test_bind_container_to_app(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel()
    mock_client = AsyncMock(spec=httpx.AsyncClient)

    container = build_container(repo=mock_repo, http_client=mock_client)
    app = FastAPI()
    bind_container_to_app(app, container)

    self.assertIs(app.state.repo, container.repo)
    self.assertIs(app.state.runtime_state, container.runtime_state)
    self.assertIs(app.state.power_tracker, container.power_tracker)
    self.assertIs(app.state.ptero, container.ptero)
    self.assertIs(app.state.steam, container.steam)
    self.assertIs(app.state.discord, container.discord)
    self.assertIs(app.state.a2s, container.a2s)
    self.assertIs(app.state.countdown, container.countdown)
    self.assertIs(app.state.preview_store, container.preview_store)
    self.assertIs(app.state.simulator_store, container.simulator_store)
    self.assertIs(app.state.orchestrator, container.orchestrator)
    self.assertIs(app.state.server_service, container.server_service)
    self.assertIs(app.state.status_service, container.status_service)
    self.assertIs(app.state.announcements, container.announcements)
    self.assertIs(app.state.call_tracker, container.call_tracker)
    self.assertIs(app.state.container, container)

  async def test_shutdown_container_cancels_tasks_and_closes_resources(self):
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    container = build_container(repo=mock_repo, http_client=mock_client)

    # Simulate an active countdown task
    async def dummy_countdown():
      try:
        await asyncio.sleep(100)
      except asyncio.CancelledError:
        pass

    task = asyncio.create_task(dummy_countdown())
    container.countdown.start("srv-test", 900, task=task)
    self.assertTrue(container.countdown.is_running("srv-test"))

    await shutdown_container(container)

    self.assertFalse(container.countdown.is_running("srv-test"))
    self.assertTrue(task.done())
    mock_client.aclose.assert_called_once()

  def test_create_announcement_service_factory(self):
    mock_repo = MagicMock()
    mock_ptero = AsyncMock()
    mock_steam = AsyncMock()
    service = create_announcement_service(
        repository=mock_repo,
        ptero=mock_ptero,
        steam=mock_steam,
    )
    self.assertIsNotNone(service)

  def test_create_update_orchestrator_factory(self):
    mock_repo = MagicMock()
    mock_ptero = AsyncMock()
    mock_steam = AsyncMock()
    mock_countdown = MagicMock()
    mock_announcements = MagicMock()
    mock_simulator = MagicMock()
    mock_runtime_state = MagicMock()

    orchestrator = create_update_orchestrator(
        repository=mock_repo,
        ptero=mock_ptero,
        steam=mock_steam,
        countdown=mock_countdown,
        announcements=mock_announcements,
        simulator_store=mock_simulator,
        runtime_state=mock_runtime_state,
    )
    self.assertIsInstance(orchestrator, UpdateOrchestratorProtocol)

  async def test_shutdown_container_closes_http_client_even_if_orchestrator_raises(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_orchestrator = MagicMock()
    mock_orchestrator.stop_loop.side_effect = RuntimeError("Fatal crash during stop_loop")

    mock_container = MagicMock(spec=ApplicationContainer)
    mock_container.orchestrator = mock_orchestrator
    mock_container.http_client = mock_client

    await shutdown_container(mock_container)

    mock_orchestrator.stop_loop.assert_called_once()
    mock_client.aclose.assert_called_once()


if __name__ == "__main__":
  unittest.main()
