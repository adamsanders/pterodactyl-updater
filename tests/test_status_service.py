import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.config import APP_VERSION, COMMIT_CODE
from app.core.models import AppConfigModel, ServerModel, WebhookPreview
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

  async def test_countdown_cancelled_on_manual_power_change(self):
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

    # Countdown should be stopped
    self.countdown.stop.assert_called_once_with("srv_enshrouded")
    self.assertIn("Manual offline detected", srv.last_status)
    # Repo should have saved the dirty config
    self.repo.save.assert_called_once_with(cfg)

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


if __name__ == "__main__":
  unittest.main()

