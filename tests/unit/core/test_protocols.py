import unittest
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.adapters.a2s import A2SAdapter
from app.adapters.discord import DiscordAdapter
from app.adapters.power_tracker import PowerStateTracker
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.repository import ConfigRepository
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.core.protocols import (
    A2SGateway,
    ConfigRepositoryGateway,
    ConfigRepositoryProtocol,
    CountdownGateway,
    CountdownManagerProtocol,
    NotificationGateway,
    PlayerQueryGateway,
    PowerTrackerGateway,
    PterodactylGateway,
    StatusAggregationGateway,
    SteamGateway,
)
from app.services.countdown import CountdownManager
from app.services.status_service import StatusAggregationService


class TestProtocolConformance(unittest.TestCase):
  """Automated contract verification test suite for runtime-checkable protocols."""

  def test_steam_adapter_conforms_to_steam_gateway(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = SteamAdapter(mock_client)
    self.assertIsInstance(adapter, SteamGateway)

  def test_simulated_steam_adapter_conforms_to_steam_gateway(self):
    mock_real = AsyncMock()
    mock_store = MagicMock()
    mock_repo = MagicMock()
    adapter = SimulatedSteamAdapter(
        real_steam=mock_real,
        simulator_store=mock_store,
        repository=mock_repo,
    )
    self.assertIsInstance(adapter, SteamGateway)

  def test_pterodactyl_adapter_conforms_to_pterodactyl_gateway(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = PterodactylAdapter(mock_client)
    self.assertIsInstance(adapter, PterodactylGateway)

  def test_discord_adapter_conforms_to_notification_gateway(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    adapter = DiscordAdapter(mock_client)
    self.assertIsInstance(adapter, NotificationGateway)

  def test_a2s_adapter_conforms_to_player_query_gateway(self):
    adapter = A2SAdapter()
    self.assertIsInstance(adapter, PlayerQueryGateway)
    self.assertIsInstance(adapter, A2SGateway)

  def test_config_repository_conforms_to_config_repository_gateway(self):
    repo = ConfigRepository()
    self.assertIsInstance(repo, ConfigRepositoryGateway)
    self.assertIsInstance(repo, ConfigRepositoryProtocol)

  def test_countdown_manager_conforms_to_countdown_gateway(self):
    manager = CountdownManager()
    self.assertIsInstance(manager, CountdownGateway)
    self.assertIsInstance(manager, CountdownManagerProtocol)

  def test_power_state_tracker_conforms_to_power_tracker_gateway(self):
    tracker = PowerStateTracker()
    self.assertIsInstance(tracker, PowerTrackerGateway)

  def test_status_aggregation_service_conforms_to_status_aggregation_gateway(self):
    mock_repo = MagicMock()
    mock_ptero = AsyncMock()
    mock_countdown = MagicMock()
    mock_preview = MagicMock()
    service = StatusAggregationService(
        repository=mock_repo,
        ptero=mock_ptero,
        countdown=mock_countdown,
        preview_store=mock_preview,
    )
    self.assertIsInstance(service, StatusAggregationGateway)

  def test_non_conforming_classes_fail_protocol_check(self):
    class IncompleteSteamAdapter:
      async def get_latest_build(self, app_id: str, server_id=None):
        pass
      # Missing fetch_patchnotes and search_games

    incomplete_steam = IncompleteSteamAdapter()
    self.assertNotIsInstance(incomplete_steam, SteamGateway)

    class IncompleteNotificationAdapter:
      pass

    self.assertNotIsInstance(IncompleteNotificationAdapter(), NotificationGateway)

    class IncompletePowerTracker:
      def invalidate(self, server_id=None):
        pass

    self.assertNotIsInstance(IncompletePowerTracker(), PowerTrackerGateway)

    class IncompleteConfigRepository:
      def load(self):
        pass
      # Missing save

    self.assertNotIsInstance(IncompleteConfigRepository(), ConfigRepositoryGateway)

    class IncompletePterodactylAdapter:
      async def get_external_ip(self):
        pass
      # Missing trigger_restart, rename_server, etc.

    self.assertNotIsInstance(IncompletePterodactylAdapter(), PterodactylGateway)

    class IncompletePlayerQuery:
      pass

    self.assertNotIsInstance(IncompletePlayerQuery(), PlayerQueryGateway)

    class IncompleteCountdown:
      def start(self, server_id, duration_seconds=900, task=None):
        pass
      # Missing is_running, get_remaining, etc.

    self.assertNotIsInstance(IncompleteCountdown(), CountdownGateway)

    class IncompleteStatusAggregation:
      async def get_single_server_status(self, cfg, ext_ip, idx, srv):
        pass
      # Missing get_status_snapshot

    self.assertNotIsInstance(IncompleteStatusAggregation(), StatusAggregationGateway)

  def test_simulated_steam_adapter_resolves_route_search(self):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.server_service import ServerService
    from app.core.models import AppConfigModel

    mock_real = AsyncMock()
    mock_real.search_games.return_value = [{"app_id": "2278520", "name": "Enshrouded"}]
    mock_store = MagicMock()
    mock_repo = MagicMock()
    mock_repo.load.return_value = AppConfigModel()

    simulated = SimulatedSteamAdapter(
        real_steam=mock_real,
        simulator_store=mock_store,
        repository=mock_repo,
    )

    old_steam = getattr(app.state, "steam", None)
    old_server_service = getattr(app.state, "server_service", None)
    try:
      app.state.steam = simulated
      app.state.server_service = ServerService(
          repository=mock_repo,
          ptero=AsyncMock(),
          steam=simulated,
          announcements=MagicMock(),
          countdown=MagicMock(),
          simulator_store=mock_store,
      )

      client = TestClient(app, raise_server_exceptions=True)
      res = client.get("/api/steam/search?q=enshrouded")
      self.assertEqual(res.status_code, 200)
      data = res.json()
      self.assertEqual(data["status"], "ok")
      self.assertEqual(data["results"], [{"app_id": "2278520", "name": "Enshrouded"}])
    finally:
      if old_steam is not None:
        app.state.steam = old_steam
      elif hasattr(app.state, "steam"):
        delattr(app.state, "steam")
      if old_server_service is not None:
        app.state.server_service = old_server_service
      elif hasattr(app.state, "server_service"):
        delattr(app.state, "server_service")



if __name__ == "__main__":
  unittest.main()
