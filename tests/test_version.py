import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.core.config import APP_VERSION, COMMIT_CODE, resolve_commit_code
from app.main import app
from app.core.models import AppConfigModel


class TestAppVersionAndCommit(unittest.TestCase):

  def test_app_version_defined_and_formatted(self):
    self.assertIsInstance(APP_VERSION, str)
    self.assertEqual(APP_VERSION, "1.18.0")
    # Check semver pattern (e.g. 1.1.0)
    parts = APP_VERSION.split(".")
    self.assertGreaterEqual(len(parts), 2)
    self.assertTrue(parts[0].isdigit())

  def test_commit_code_defined_and_formatted(self):
    self.assertIsInstance(COMMIT_CODE, str)
    self.assertTrue(len(COMMIT_CODE) > 0)
    self.assertLessEqual(len(COMMIT_CODE), 7)
    self.assertNotEqual(COMMIT_CODE, "unknown")

  def test_resolve_commit_code_env_override(self):
    with patch.dict(os.environ, {"GIT_COMMIT": "abcdef123456"}):
      resolved = resolve_commit_code()
      self.assertEqual(resolved, "abcdef1")

  def test_resolve_commit_code_ignores_unknown_env(self):
    with patch.dict(os.environ, {"GIT_COMMIT": "unknown"}):
      resolved = resolve_commit_code()
      self.assertNotEqual(resolved, "unknown")
      self.assertGreaterEqual(len(resolved), 7)

  def test_resolve_commit_code_from_file_and_fallback(self):
    with patch.dict(os.environ, {"GIT_COMMIT": ""}, clear=True), \
         patch("subprocess.check_output", side_effect=Exception("no git")), \
         patch("os.path.isfile", return_value=False):
      resolved = resolve_commit_code()
      self.assertNotEqual(resolved, "unknown")
      self.assertGreaterEqual(len(resolved), 7)

  def test_fastapi_app_has_version(self):
    self.assertEqual(app.version, APP_VERSION)

  def test_dashboard_and_status_api_contain_version_and_commit(self):
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
    self.assertIn(f"commit {COMMIT_CODE}", res.text)
    self.assertIn('id="app-commit"', res.text)
    self.assertIn('name="ssl_verify"', res.text)
    self.assertIn('id="ssl_verify"', res.text)
    self.assertIn("Verify SSL Certificates", res.text)
    self.assertIn('/static/js/dashboard.js', res.text)

    # 2. Test Static Files mounting for dashboard.js
    res_static = client.get("/static/js/dashboard.js")
    self.assertEqual(res_static.status_code, 200)
    self.assertIn("function makeDraggable", res_static.text)

    # 3. Test JSON status API
    res_api = client.get("/api/status")
    self.assertEqual(res_api.status_code, 200)
    data = res_api.json()
    self.assertEqual(data.get("app_version"), APP_VERSION)
    self.assertEqual(data.get("commit_code"), COMMIT_CODE)


if __name__ == "__main__":
  unittest.main()

