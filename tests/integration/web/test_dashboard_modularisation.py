import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.core.config import APP_VERSION, COMMIT_CODE
from app.core.models import AppConfigModel, ServerModel
from app.web.schemas import WebhookPreview
from app.main import app
from app.web.templating import templates


class TestDashboardModularisation(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.base_dir = Path(__file__).resolve().parents[3]
    cls.templates_dir = cls.base_dir / "app" / "web" / "templates"
    cls.components_dir = cls.templates_dir / "components"
    cls.static_js_dir = cls.base_dir / "app" / "web" / "static" / "js"

  def setUp(self):
    app.state.repo = MagicMock()
    app.state.repo.load.return_value = AppConfigModel(
        panel_url="https://panel.example.com",
        api_key="ptlc_test_key",
        check_interval=5,
        discord_webhook="https://discord.com/api/webhooks/test",
        test_mode=True,
        ssl_verify=True,
        last_check="2026-10-16 12:00:00",
        servers=[
            ServerModel(
                server_id="srv-alpha",
                name="Survival Server",
                app_id="896660",
                manifest_path="steamapps/appmanifest_896660.acf",
                query_port_offset=0,
                auto_restart=True,
                discord_alerts=True,
                warn_ingame_countdown=True,
                warn_discord_countdown=True,
                current_build="1000",
                latest_build="1000",
            ),
            ServerModel(
                server_id="srv-beta",
                name="Creative Server",
                app_id="294100",
                manifest_path="steamapps/appmanifest_294100.acf",
                query_port_offset=10,
                auto_restart=False,
                discord_alerts=False,
                warn_ingame_countdown=False,
                warn_discord_countdown=False,
                current_build="1000",
                latest_build="2000",
            ),
        ],
    )
    app.state.countdown = MagicMock()
    app.state.countdown.get_remaining.side_effect = lambda sid: 300 if sid == "srv-beta" else 0
    app.state.countdown.get_target.side_effect = lambda sid: 1770000000.0 if sid == "srv-beta" else 0.0
    app.state.countdown.is_running.side_effect = lambda sid: sid == "srv-beta"

    app.state.preview_store = MagicMock()
    app.state.preview_store.get_preview.return_value = {
        "timestamp": "12:00",
        "formatted_message": "Update available",
        "embed": None,
    }

    app.state.ptero = AsyncMock()
    app.state.ptero.get_external_ip.return_value = "1.2.3.4"
    app.state.ptero.get_power_state.return_value = "running"
    app.state.ptero.consume_startup_transition.return_value = False
    app.state.ptero.get_server_allocation.return_value = ("1.2.3.4", 2456)
    app.state.a2s = AsyncMock()
    app.state.a2s.get_player_count.return_value = (5, 20)
    app.state.orchestrator = MagicMock()
    app.state.call_tracker = MagicMock()
    app.state.server_service = MagicMock()
    app.state.commit_code = COMMIT_CODE

    self.client = TestClient(app, raise_server_exceptions=True)

  def test_component_files_exist_on_filesystem(self):
    expected_components = [
        "_global_status.html",
        "_settings_panel.html",
        "_server_card.html",
        "_footer.html",
        "_modals.html",
        "_console_modal.html",
        "_simulator_modal.html",
    ]
    for comp in expected_components:
      comp_path = self.components_dir / comp
      self.assertTrue(comp_path.exists(), f"Component missing: {comp_path}")
      self.assertGreater(comp_path.stat().st_size, 0, f"Component empty: {comp_path}")

  def test_root_template_shims_are_removed(self):
    root_shims = [
        "_global_status.html",
        "_settings_panel.html",
        "_server_card.html",
        "_footer.html",
        "_modals.html",
        "_console_modal.html",
        "_simulator_modal.html",
    ]
    for shim in root_shims:
      shim_path = self.templates_dir / shim
      self.assertFalse(shim_path.exists(), f"Obsolete root shim still exists: {shim_path}")


  def test_static_dashboard_js_served(self):
    res = self.client.get("/static/js/dashboard.js")
    self.assertEqual(res.status_code, 200)
    self.assertIn("application/javascript", res.headers.get("content-type", "") or "text/javascript")
    self.assertIn("function makeDraggable", res.text)
    self.assertIn("function toggleLiveConsole", res.text)
    self.assertIn("function pollLiveStatus", res.text)
    self.assertIn("function triggerPowerAction", res.text)

  def test_all_es_modules_served(self):
    modules = [
        "toast.js",
        "domUtils.js",
        "statusPoller.js",
        "serverCard.js",
        "steamSearch.js",
        "consoleDrawer.js",
        "simulatorModal.js",
        "dragDrop.js",
    ]
    for mod in modules:
      mod_path = self.static_js_dir / "modules" / mod
      self.assertTrue(mod_path.exists(), f"Module missing on disk: {mod_path}")
      res = self.client.get(f"/static/js/modules/{mod}")
      self.assertEqual(res.status_code, 200, f"Module not served: {mod}")
      self.assertIn("application/javascript", res.headers.get("content-type", "") or "text/javascript")
      self.assertGreater(len(res.text), 50)

  def test_dashboard_renders_all_components(self):
    res = self.client.get("/")
    self.assertEqual(res.status_code, 200)

    # Static script link
    self.assertIn('<script type="module" src="/static/js/dashboard.js"></script>', res.text)

    # Settings panel elements
    self.assertIn("Global Panel Settings", res.text)
    self.assertIn('name="panel_url"', res.text)
    self.assertIn('name="api_key"', res.text)
    self.assertIn('name="check_interval"', res.text)
    self.assertIn('name="discord_webhook"', res.text)
    self.assertIn('name="test_mode"', res.text)
    self.assertIn('name="ssl_verify"', res.text)

    # Server card elements
    self.assertIn("Survival Server", res.text)
    self.assertIn("Creative Server", res.text)
    self.assertIn('id="btn_start_0"', res.text)
    self.assertIn('id="btn_restart_0"', res.text)
    self.assertIn('id="btn_stop_0"', res.text)
    self.assertIn('id="srv_save_btn_0"', res.text)
    self.assertIn('name="srv_port_offset_0"', res.text)
    self.assertIn('name="srv_port_offset_1"', res.text)

    # Build status indicators (matching builds vs differing builds)
    self.assertIn("Build:", res.text)
    self.assertIn("1000 &rarr; 2000", res.text)

    # Countdown badge for active server
    self.assertIn('id="srv_countdown_wrap_1"', res.text)
    self.assertIn("5m 0s", res.text)

    # Global Status card is rendered near the top before main-form
    self.assertIn('id="global-last-check"', res.text)
    self.assertIn('id="btn-check-now"', res.text)
    self.assertLess(res.text.index('id="btn-check-now"'), res.text.index('id="main-form"'))

    # Footer elements
    self.assertEqual(APP_VERSION, "1.30.0")
    self.assertIn(f"v{APP_VERSION}", res.text)
    self.assertIn("v1.30.0", res.text)
    self.assertIn(f"commit {COMMIT_CODE}", res.text)

    # Modals
    self.assertIn('id="test-simulator-window"', res.text)
    self.assertIn('id="live-console-window"', res.text)
    self.assertIn('id="toast-container"', res.text)

  def test_empty_server_list_renders_gracefully(self):
    app.state.repo.load.return_value = AppConfigModel(servers=[])
    res = self.client.get("/")
    self.assertEqual(res.status_code, 200)
    self.assertIn('No servers added yet. Click "+ Add Another Server" above.', res.text)

  def test_render_component_partials_directly(self):
    cfg = app.state.repo.load()

    # 1. Global status partial
    tpl_status = templates.get_template("components/_global_status.html")
    html_status = tpl_status.render(cfg=cfg)
    self.assertIn('id="global-last-check"', html_status)
    self.assertIn('id="btn-check-now"', html_status)

    # 2. Settings panel partial
    tpl_settings = templates.get_template("components/_settings_panel.html")
    html_settings = tpl_settings.render(cfg=cfg)
    self.assertIn("Global Panel Settings", html_settings)
    self.assertIn('name="panel_url"', html_settings)

    # 3. Server card partial
    tpl_card = templates.get_template("components/_server_card.html")
    html_card = tpl_card.render(
        srv=cfg.servers[0],
        idx=0,
        countdown=app.state.countdown,
    )
    self.assertIn("Survival Server", html_card)
    self.assertIn('id="btn_start_0"', html_card)

    # 4. Footer partial
    tpl_footer = templates.get_template("components/_footer.html")
    html_footer = tpl_footer.render(
        cfg=cfg,
        app_version=APP_VERSION,
        commit_code=COMMIT_CODE,
    )
    self.assertEqual(APP_VERSION, "1.30.0")
    self.assertIn(f"v{APP_VERSION}", html_footer)
    self.assertIn("v1.30.0", html_footer)
    self.assertIn(f"commit {COMMIT_CODE}", html_footer)

    # 5. Modals partial
    tpl_modals = templates.get_template("components/_modals.html")
    html_modals = tpl_modals.render(cfg=cfg)
    self.assertIn('id="test-simulator-window"', html_modals)
    self.assertIn('id="live-console-window"', html_modals)
    self.assertIn('id="toast-container"', html_modals)

  def test_preview_renders_in_simulator_modal_and_dashboard(self):
    cfg = app.state.repo.load()
    preview = WebhookPreview(
        server_name="Survival Server",
        message="Update available for **Survival Server**! Restarting soon.",
        embed={
            "title": "Steam v2.0 Patch",
            "url": "https://store.steampowered.com/news/12345",
            "description": "Critical security and content patch.",
            "image": {"url": "https://steamcdn-a.akamaihd.net/header.jpg"},
            "footer": {"text": "Steam Web API Feed"},
        },
        timestamp="14:30:00",
    )

    # 1. Direct modal rendering with WebhookPreview instance
    tpl_sim = templates.get_template("components/_simulator_modal.html")
    html_sim = tpl_sim.render(cfg=cfg, preview=preview)

    self.assertIn("14:30:00", html_sim)
    self.assertIn("Update available for", html_sim)
    self.assertIn("Survival Server", html_sim)
    self.assertIn("Steam v2.0 Patch", html_sim)
    self.assertIn("https://store.steampowered.com/news/12345", html_sim)
    self.assertIn("Critical security and content patch.", html_sim)
    self.assertIn("https://steamcdn-a.akamaihd.net/header.jpg", html_sim)
    self.assertIn("Steam Web API Feed", html_sim)
    self.assertIn('id="sim-preview-empty" class="hidden', html_sim)
    self.assertNotIn('id="sim-preview-container" class="hidden', html_sim)

    # 2. Direct modal rendering with None preview
    html_sim_none = tpl_sim.render(cfg=cfg, preview=None)
    self.assertIn('id="sim-preview-container" class="hidden', html_sim_none)
    self.assertNotIn('id="sim-preview-empty" class="hidden', html_sim_none)

    # 3. HTTP GET route rendering with active preview
    app.state.preview_store.get_preview.return_value = preview
    res = self.client.get("/")
    self.assertEqual(res.status_code, 200)
    self.assertIn("Steam v2.0 Patch", res.text)
    self.assertIn("14:30:00", res.text)

  def test_components_render_with_empty_or_none_context_gracefully(self):
    # Tests that every single modular template can render safely without throwing UndefinedError
    # when variables are omitted or passed as None

    # 1. Global status with zero variables
    tpl_status = templates.get_template("components/_global_status.html")
    html_status = tpl_status.render()
    self.assertIn('id="btn-check-now"', html_status)
    self.assertIn('id="global-last-check"', html_status)

    # 2. Footer with zero variables
    tpl_footer = templates.get_template("components/_footer.html")
    html_footer = tpl_footer.render()
    self.assertIn('id="app-commit"', html_footer)

    # 3. Settings panel with zero variables
    tpl_settings = templates.get_template("components/_settings_panel.html")
    html_settings = tpl_settings.render()
    self.assertIn("Global Panel Settings", html_settings)

    # 4. Simulator modal with zero variables
    tpl_sim = templates.get_template("components/_simulator_modal.html")
    html_sim = tpl_sim.render()
    self.assertIn('id="test-simulator-window"', html_sim)

    # 5. Modals partial with zero variables
    tpl_modals = templates.get_template("components/_modals.html")
    html_modals = tpl_modals.render()
    self.assertIn('id="toast-container"', html_modals)

    # 6. Server card with countdown=None
    srv = ServerModel(
        server_id="srv-solo",
        name="Solo Server",
        app_id="123",
        manifest_path="acf",
    )
    tpl_card = templates.get_template("components/_server_card.html")
    html_card = tpl_card.render(srv=srv, countdown=None)
    self.assertIn("Solo Server", html_card)
    self.assertIn('id="btn_start_0"', html_card)

    # 6. Top-level dashboard with zero variables
    tpl_dash = templates.get_template("dashboard.html")
    html_dash = tpl_dash.render()
    self.assertIn("Pterodactyl Multi-Server Auto-Updater", html_dash)
    self.assertIn('id="main-form"', html_dash)

  def test_version_context_variable_alias_supported(self):
    # Requirement: cfg, version, commit_code, countdown, preview continue to render
    tpl_footer = templates.get_template("components/_footer.html")
    html_footer = tpl_footer.render(version="9.9.9", commit_code="1a2b3c4")
    self.assertIn("v9.9.9", html_footer)
    self.assertIn("commit 1a2b3c4", html_footer)

    tpl_dash = templates.get_template("dashboard.html")
    html_dash = tpl_dash.render(version="9.9.9")
    self.assertIn("v9.9.9", html_dash)


if __name__ == "__main__":
  unittest.main()
