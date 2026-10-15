import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.config import APP_VERSION
from app.main import app
from app.core.models import AppConfigModel


class TestAppVersion(unittest.TestCase):

  def test_app_version_defined_and_formatted(self):
    self.assertIsInstance(APP_VERSION, str)
    self.assertTrue(len(APP_VERSION) > 0)
    # Check semver pattern (e.g. 1.1.0)
    parts = APP_VERSION.split(".")
    self.assertGreaterEqual(len(parts), 2)
    self.assertTrue(parts[0].isdigit())

  def test_fastapi_app_has_version(self):
    self.assertEqual(app.version, APP_VERSION)

  def test_dashboard_and_status_api_contain_version(self):
    # Mock dependencies stored in app.state
    app.state.repo = MagicMock()
    app.state.repo.load.return_value = AppConfigModel(last_check="2026-10-15 12:00:00")
    app.state.countdown = MagicMock()
    app.state.countdown.get_remaining.return_value = 0
    app.state.countdown.get_target.return_value = 0.0
    app.state.countdown.is_running.return_value = False
    app.state.preview_store = MagicMock()
    app.state.preview_store.get_preview.return_value = None
    app.state.ptero = AsyncMock()
    app.state.ptero.get_external_ip.return_value = "1.2.3.4"
    app.state.ptero.get_power_state.return_value = "running"
    app.state.ptero.consume_startup_transition.return_value = False
    app.state.ptero.get_server_allocation.return_value = ("1.2.3.4", 2456)
    app.state.a2s = AsyncMock()
    app.state.a2s.get_player_count.return_value = (0, 10)
    app.state.orchestrator = MagicMock()
    app.state.call_tracker = MagicMock()
    app.state.server_service = MagicMock()

    client = TestClient(app, raise_server_exceptions=True)

    # 1. Test HTML Dashboard
    res = client.get("/")
    self.assertEqual(res.status_code, 200)
    self.assertIn(f"v{APP_VERSION}", res.text)
    self.assertIn('id="app-version"', res.text)

    # 2. Test JSON status API
    res_api = client.get("/api/status")
    self.assertEqual(res_api.status_code, 200)
    data = res_api.json()
    self.assertEqual(data.get("app_version"), APP_VERSION)


if __name__ == "__main__":
  unittest.main()
