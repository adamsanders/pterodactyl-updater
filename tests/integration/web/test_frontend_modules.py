import re
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app


class TestFrontendModularArchitecture(unittest.TestCase):
  """Integration tests verifying ES module decomposition, static file delivery, and DOM security."""

  @classmethod
  def setUpClass(cls):
    cls.base_dir = Path(__file__).resolve().parents[3]
    cls.js_dir = cls.base_dir / "app" / "web" / "static" / "js"
    cls.modules_dir = cls.js_dir / "modules"
    cls.templates_dir = cls.base_dir / "app" / "web" / "templates"
    cls.client = TestClient(app, raise_server_exceptions=True)

  def test_modules_directory_contains_all_eight_es_modules(self):
    expected_modules = [
        "toast.js",
        "domUtils.js",
        "statusPoller.js",
        "serverCard.js",
        "steamSearch.js",
        "consoleDrawer.js",
        "simulatorModal.js",
        "dragDrop.js",
    ]
    for mod in expected_modules:
      mod_path = self.modules_dir / mod
      self.assertTrue(mod_path.is_file(), f"Expected module missing: {mod_path}")
      self.assertGreater(mod_path.stat().st_size, 100, f"Module unexpectedly small: {mod_path}")

  def test_static_routes_serve_all_modules_with_javascript_mimetype(self):
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
      res = self.client.get(f"/static/js/modules/{mod}")
      self.assertEqual(res.status_code, 200, f"Failed to fetch /static/js/modules/{mod}")
      content_type = res.headers.get("content-type", "")
      self.assertTrue(
          "application/javascript" in content_type or "text/javascript" in content_type,
          f"Unexpected content-type for {mod}: {content_type}",
      )

  def test_dashboard_js_orchestrates_all_modules_and_window_bindings(self):
    dashboard_js = (self.js_dir / "dashboard.js").read_text(encoding="utf-8")

    # Verify import statements for each module
    expected_imports = [
        "from './modules/toast.js'",
        "from './modules/domUtils.js'",
        "from './modules/dragDrop.js'",
        "from './modules/statusPoller.js'",
        "from './modules/serverCard.js'",
        "from './modules/steamSearch.js'",
        "from './modules/consoleDrawer.js'",
        "from './modules/simulatorModal.js'",
    ]
    for imp in expected_imports:
      self.assertIn(imp, dashboard_js, f"Missing import in dashboard.js: {imp}")

    # Verify window bindings for HTML inline onclick/onchange attributes
    expected_window_bindings = [
        "window.makeDraggable = makeDraggable",
        "window.toggleLiveConsole = toggleLiveConsole",
        "window.pollLiveStatus = pollLiveStatus",
        "window.triggerPowerAction = triggerPowerAction",
        "window.showToast = showToast",
        "window.triggerCheckNow = triggerCheckNow",
        "window.clearTelemetryLogs = clearTelemetryLogs",
        "window.toggleTestModeImmediate = toggleTestModeImmediate",
        "window.triggerSimulateBuild = triggerSimulateBuild",
        "window.saveSingleServer = saveSingleServer",
        "window.refreshServerName = refreshServerName",
        "window.toggleServerSlider = toggleServerSlider",
        "window.toggleEditName = toggleEditName",
        "window.openSteamAppSearch = openSteamAppSearch",
        "window.toggleSteamAppSearch = toggleSteamAppSearch",
        "window.closeSteamAppSearch = closeSteamAppSearch",
        "window.selectSteamGame = selectSteamGame",
        "window.autoSyncServerDetails = autoSyncServerDetails",
        "window.initServerDragAndDrop = initServerDragAndDrop",
        "window.initServerCardDelegation = initServerCardDelegation",
        "window.getCardContext = getCardContext",
    ]
    for binding in expected_window_bindings:
      self.assertIn(binding, dashboard_js, f"Missing window binding in dashboard.js: {binding}")

  def test_dashboard_html_loads_module_script(self):
    html_content = (self.templates_dir / "dashboard.html").read_text(encoding="utf-8")
    self.assertIn('<script type="module" src="/static/js/dashboard.js"></script>', html_content)

  def test_dom_utils_url_sanitization_rules(self):
    dom_utils_content = (self.modules_dir / "domUtils.js").read_text(encoding="utf-8")

    # Verify presence of sanitizeUrl function
    self.assertIn("function sanitizeUrl", dom_utils_content)

    # Verify that dangerous URI schemes are blocked
    self.assertIn("javascript", dom_utils_content)
    self.assertIn("data", dom_utils_content)
    self.assertIn("vbscript", dom_utils_content)

    # Verify control-character and whitespace evasion stripping
    self.assertIn("replace(/[\\x00-\\x20\\s]+/g", dom_utils_content)

    # Verify that http and https are permitted
    self.assertIn("http:", dom_utils_content)
    self.assertIn("https:", dom_utils_content)

  def test_dom_utils_create_element_sanitizes_href_and_src(self):
    dom_utils_content = (self.modules_dir / "domUtils.js").read_text(encoding="utf-8")
    self.assertIn("tagLower === 'a'", dom_utils_content)
    self.assertIn("tagLower === 'img'", dom_utils_content)
    self.assertIn("sanitizeUrl(val)", dom_utils_content)

  def test_drag_drop_exports_reindex_and_guards_interactive_controls(self):
    drag_drop_content = (self.modules_dir / "dragDrop.js").read_text(encoding="utf-8")
    self.assertIn("export function reindexServerCards", drag_drop_content)
    self.assertIn("LABEL", drag_drop_content)
    self.assertIn("button, label, input, select, textarea, a", drag_drop_content)
    self.assertIn(".server-drag-handle", drag_drop_content)
    self.assertIn("let isDragging = false;", drag_drop_content)
    self.assertIn("let isHandleGrabbed = false;", drag_drop_content)
    self.assertIn("isHandleGrabbed", drag_drop_content)

  def test_server_card_template_includes_visible_drag_anchor(self):
    server_card_tpl = (self.templates_dir / "components" / "_server_card.html").read_text(encoding="utf-8")
    self.assertIn("server-drag-handle", server_card_tpl)
    self.assertIn("cursor-grab", server_card_tpl)
    self.assertIn("active:cursor-grabbing", server_card_tpl)
    self.assertIn("Drag to reorder server", server_card_tpl)

  def test_dashboard_js_readystatus_guard_and_reindex_export(self):
    dashboard_js = (self.js_dir / "dashboard.js").read_text(encoding="utf-8")
    self.assertIn("document.readyState === 'loading'", dashboard_js)
    self.assertIn("window.reindexServerCards = reindexServerCards", dashboard_js)
    self.assertIn("updateCountdowns()", dashboard_js)

  def test_steam_search_uses_safe_dom_construction_without_inner_html_injection(self):
    steam_search_content = (self.modules_dir / "steamSearch.js").read_text(encoding="utf-8")

    # Verify safe element creation instead of vulnerable template string concatenation
    self.assertIn("document.createElement", steam_search_content)
    self.assertIn("textContent", steam_search_content)
    self.assertNotIn("resultsContainer.innerHTML = data.results.map", steam_search_content)

  def test_simulator_modal_uses_safe_dom_and_sanitizes_links(self):
    simulator_content = (self.modules_dir / "simulatorModal.js").read_text(encoding="utf-8")

    # Verify safe link construction and URL sanitization
    self.assertIn("sanitizeUrl", simulator_content)
    self.assertNotIn("titleEl.innerHTML = `<a href=\"${preview.embed.url}\"", simulator_content)

  def test_status_poller_computes_visual_card_number_from_dom(self):
    status_poller_content = (self.modules_dir / "statusPoller.js").read_text(encoding="utf-8")
    self.assertIn("allTitles.indexOf(titleEl)", status_poller_content)
    self.assertIn("cardNum", status_poller_content)

  def test_server_card_module_exports_delegation_functions(self):
    server_card_content = (self.modules_dir / "serverCard.js").read_text(encoding="utf-8")
    self.assertIn("export function initServerCardDelegation", server_card_content)
    self.assertIn("export function getCardContext", server_card_content)
    self.assertIn("data-action", server_card_content)
    self.assertIn("save-server", server_card_content)
    self.assertIn("sync-name", server_card_content)
    self.assertIn("power-action", server_card_content)

  def test_templates_contain_event_delegation_attributes(self):
    card_tpl = (self.templates_dir / "components" / "_server_card.html").read_text(encoding="utf-8")
    self.assertIn('data-server-card', card_tpl)
    self.assertIn('data-action="save-server"', card_tpl)
    self.assertIn('data-action="sync-name"', card_tpl)
    self.assertIn('data-action="power-action"', card_tpl)
    self.assertIn('data-action="toggle-edit-name"', card_tpl)
    self.assertIn('data-action="toggle-slider"', card_tpl)
    self.assertIn('data-action="server-text-input"', card_tpl)
    self.assertIn('data-action="server-id-input"', card_tpl)
    self.assertIn('data-action="steam-appid-input"', card_tpl)
    self.assertNotIn('onclick=', card_tpl)
    self.assertNotIn('onchange=', card_tpl)
    self.assertNotIn('oninput=', card_tpl)

    status_tpl = (self.templates_dir / "components" / "_global_status.html").read_text(encoding="utf-8")
    self.assertIn('data-action="check-now"', status_tpl)
    self.assertNotIn('onclick=', status_tpl)

    settings_tpl = (self.templates_dir / "components" / "_settings_panel.html").read_text(encoding="utf-8")
    self.assertIn('data-action="toggle-test-mode"', settings_tpl)
    self.assertIn('data-action="toggle-live-console"', settings_tpl)
    self.assertNotIn('onclick=', settings_tpl)
    self.assertNotIn('onchange=', settings_tpl)

    simulator_tpl = (self.templates_dir / "components" / "_simulator_modal.html").read_text(encoding="utf-8")
    self.assertIn('data-action="clear-preview"', simulator_tpl)
    self.assertIn('data-action="close-modal"', simulator_tpl)
    self.assertIn('data-action="simulate-build"', simulator_tpl)
    self.assertNotIn('onclick=', simulator_tpl)

    console_tpl = (self.templates_dir / "components" / "_console_modal.html").read_text(encoding="utf-8")
    self.assertIn('data-action="clear-telemetry"', console_tpl)
    self.assertIn('data-action="toggle-live-console"', console_tpl)
    self.assertNotIn('onclick=', console_tpl)

  def test_delegation_guard_and_context_resolution(self):
    server_card_content = (self.modules_dir / "serverCard.js").read_text(encoding="utf-8")
    self.assertIn("_serverCardDelegationInitialized", server_card_content)
    self.assertIn("typeof actionEl.onclick === 'function'", server_card_content)
    self.assertIn("typeof target.oninput === 'function'", server_card_content)
    self.assertIn("typeof target.onchange === 'function'", server_card_content)
    self.assertIn("element.closest('[data-server-card]')", server_card_content)
    self.assertIn("element.dataset?.cardIndex", server_card_content)


if __name__ == "__main__":
  unittest.main()
