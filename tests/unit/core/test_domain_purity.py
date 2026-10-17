import unittest
import warnings

from app.adapters.discord import DiscordAdapter
from app.adapters.power_tracker import PowerTrackerEntry
from app.adapters.vcs import resolve_commit_code
from app.core.config import APP_VERSION, DEFAULT_COMMIT_CODE, get_commit_code
from app.core.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    PterodactylApiError,
    UnauthorizedError,
    ValidationError,
)
from app.core.models import (
    DetectedServerDetails,
    NotificationPreview,
    PowerState,
    SaveServerCommand,
    SaveSettingsCommand,
    ServerModel,
    SteamPatchNotes,
    SteamSearchResult,
    _raise_domain_error,
)
from app.core.protocols import (
    BuildSimulatorProtocol,
    NotificationGateway,
    WebhookPreviewStoreProtocol,
)
from app.services.build_simulator import BuildSimulatorStore
from app.services.preview_store import WebhookPreviewStore
from app.web.schemas import (
    SettingsUpdateDTO,
    SingleServerSaveRequest,
    WebhookPreview,
)


class TestDomainCommands(unittest.IsolatedAsyncioTestCase):
  """Validates domain command data models and web schema polymorphism."""

  def test_save_settings_command_defaults(self):
    cmd = SaveSettingsCommand()
    self.assertEqual(cmd.panel_url, "")
    self.assertEqual(cmd.api_key, "")
    self.assertEqual(cmd.check_interval, 15)
    self.assertEqual(cmd.discord_webhook, "")
    self.assertFalse(cmd.test_mode)
    self.assertFalse(cmd.ssl_verify)
    self.assertEqual(cmd.servers, [])

  def test_save_settings_command_explicit(self):
    srv = ServerModel(server_id="s1", name="Server 1")
    cmd = SaveSettingsCommand(
        panel_url="https://panel.test",
        api_key="secret",
        check_interval=5,
        discord_webhook="https://discord.test",
        test_mode=True,
        ssl_verify=True,
        servers=[srv],
    )
    self.assertEqual(cmd.panel_url, "https://panel.test")
    self.assertEqual(cmd.api_key, "secret")
    self.assertEqual(cmd.check_interval, 5)
    self.assertTrue(cmd.test_mode)
    self.assertTrue(cmd.ssl_verify)
    self.assertEqual(len(cmd.servers), 1)

  def test_save_server_command_defaults_and_explicit(self):
    cmd_def = SaveServerCommand()
    self.assertEqual(cmd_def.server_id, "")
    self.assertEqual(cmd_def.name, "")
    self.assertEqual(cmd_def.app_id, "")
    self.assertEqual(cmd_def.query_port_offset, 0)

    cmd = SaveServerCommand(
        server_id="srv-1",
        name="My Server",
        app_id="896660",
        manifest_path="manifest.acf",
        query_port_offset=1,
        broadcast_command_template="say {message}",
    )
    self.assertEqual(cmd.server_id, "srv-1")
    self.assertEqual(cmd.query_port_offset, 1)

  def test_notification_preview_model(self):
    prev = NotificationPreview(
        server_name="Test Game",
        message="Update available",
        embed={"title": "Patch"},
        timestamp="12:00 PM",
    )
    self.assertEqual(prev.server_name, "Test Game")
    self.assertEqual(prev.message, "Update available")
    self.assertEqual(prev.embed, {"title": "Patch"})
    self.assertEqual(prev.timestamp, "12:00 PM")

  def test_web_schemas_inherit_from_domain_commands(self):
    self.assertTrue(issubclass(SingleServerSaveRequest, SaveServerCommand))
    self.assertTrue(issubclass(SettingsUpdateDTO, SaveSettingsCommand))
    self.assertTrue(issubclass(WebhookPreview, NotificationPreview))

    # Polymorphic .to_command()
    req = SingleServerSaveRequest(server_id="srv-1", name="Test")
    cmd = req.to_command()
    self.assertIsInstance(cmd, SaveServerCommand)
    self.assertEqual(cmd.server_id, "srv-1")
    self.assertIn("name", cmd.model_fields_set)
    self.assertNotIn("app_id", cmd.model_fields_set)
    self.assertNotIn("manifest_path", cmd.model_fields_set)

    dto = SettingsUpdateDTO(panel_url="https://panel.test", api_key="key", servers=[])
    cmd_settings = dto.to_command()
    self.assertIsInstance(cmd_settings, SaveSettingsCommand)
    self.assertEqual(cmd_settings.panel_url, "https://panel.test")

    prev = WebhookPreview(server_name="Game", message="Msg", timestamp="12:00")
    cmd_preview = prev.to_command()
    self.assertIsInstance(cmd_preview, NotificationPreview)
    self.assertEqual(cmd_preview.server_name, "Game")

  async def test_settings_form_data_to_command(self):
    from starlette.datastructures import FormData
    from app.web.schemas import SettingsFormData
    form = FormData([
        ("panel_url", "https://panel.example.com"),
        ("api_key", "secret-token"),
        ("check_interval", "30"),
        ("discord_webhook", "https://discord.example.com/webhook"),
    ])
    cmd = await SettingsFormData.to_command(form, [])
    self.assertIsInstance(cmd, SaveSettingsCommand)
    self.assertEqual(cmd.panel_url, "https://panel.example.com")
    self.assertEqual(cmd.check_interval, 30)


class TestDomainExceptionsHierarchy(unittest.TestCase):
  """Validates normalized domain exception inheritance from DomainError."""

  def test_exceptions_inherit_from_domain_error(self):
    self.assertTrue(issubclass(ValidationError, DomainError))
    self.assertTrue(issubclass(NotFoundError, DomainError))
    self.assertTrue(issubclass(ConflictError, DomainError))
    self.assertTrue(issubclass(UnauthorizedError, DomainError))

  def test_exception_status_codes_and_defaults(self):
    ve = ValidationError("Invalid value")
    self.assertEqual(ve.status_code, 400)
    self.assertEqual(str(ve), "Invalid value")
    self.assertEqual(ve.args[0], "Invalid value")

    ne = NotFoundError("Item missing")
    self.assertEqual(ne.status_code, 404)

    ce = ConflictError("State conflict")
    self.assertEqual(ce.status_code, 409)

    ue = UnauthorizedError("Bad auth")
    self.assertEqual(ue.status_code, 401)

  def test_exception_custom_status_code(self):
    ve = ValidationError("Unprocessable", status_code=422)
    self.assertEqual(ve.status_code, 422)

    de = DomainError("Custom error", status_code=500)
    self.assertEqual(de.status_code, 500)

  def test_raise_domain_error_generic_fallback_raises_domain_error(self):
    with self.assertRaises(DomainError) as ctx:
      _raise_domain_error("Unknown gateway timeout occurred", status_code=400)
    self.assertIs(type(ctx.exception), DomainError)
    self.assertNotIsInstance(ctx.exception, PterodactylApiError)
    self.assertEqual(ctx.exception.status_code, 400)


class TestDomainProtocols(unittest.TestCase):
  """Validates runtime protocols decouple domain services from concrete adapters."""

  def test_build_simulator_protocol_conformance(self):
    self.assertTrue(issubclass(BuildSimulatorStore, BuildSimulatorProtocol))
    store = BuildSimulatorStore()
    self.assertIsInstance(store, BuildSimulatorProtocol)

    store.set_simulated_build("srv-test", "12345")
    self.assertEqual(store.get_simulated_build("srv-test"), "12345")
    store.clear_simulated_build("srv-test")
    self.assertIsNone(store.get_simulated_build("srv-test"))

  def test_webhook_preview_store_protocol_conformance(self):
    self.assertTrue(issubclass(WebhookPreviewStore, WebhookPreviewStoreProtocol))
    store = WebhookPreviewStore()
    self.assertIsInstance(store, WebhookPreviewStoreProtocol)

    preview = NotificationPreview(server_name="Game", message="Notes", timestamp="12:00 PM")
    store.set_preview(preview)
    self.assertIsNotNone(store.get_preview())
    store.clear()
    self.assertIsNone(store.get_preview())

  def test_notification_gateway_create_patchnotes_embed(self):
    self.assertTrue(hasattr(NotificationGateway, "create_patchnotes_embed"))
    notes = SteamPatchNotes(
        title="Update v1.0",
        url="https://steam.test/news/1",
        content="Details",
    )
    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertIn("Update v1.0", embed["title"])
    self.assertEqual(embed["url"], "https://steam.test/news/1")


class TestDictEmulationPurge(unittest.TestCase):
  """Validates dictionary emulation methods have been cleanly purged."""

  def test_detected_server_details_no_dict_subscript(self):
    details = DetectedServerDetails(name="Valheim", app_id="896660")
    self.assertEqual(details.name, "Valheim")
    self.assertEqual(details.app_id, "896660")
    with self.assertRaises(TypeError):
      _ = details["name"]
    with self.assertRaises(AttributeError):
      _ = details.get("name")

  def test_steam_search_result_no_dict_subscript_and_no_dict_eq(self):
    res = SteamSearchResult(app_id="896660", name="Valheim")
    self.assertEqual(res.app_id, "896660")
    self.assertEqual(res.name, "Valheim")
    with self.assertRaises(TypeError):
      _ = res["app_id"]
    self.assertNotEqual(res, {"app_id": "896660", "name": "Valheim"})

  def test_power_tracker_entry_no_dict_subscript(self):
    entry = PowerTrackerEntry(raw_state=PowerState.STARTING)
    self.assertEqual(entry.raw_state, PowerState.STARTING)
    with self.assertRaises(TypeError):
      _ = entry["raw_state"]


class TestConfigAndVcsDecoupling(unittest.TestCase):
  """Validates config purity and VCS resolution decoupling."""

  def test_config_get_commit_code_is_pure_and_deterministic(self):
    self.assertEqual(get_commit_code(), DEFAULT_COMMIT_CODE)
    self.assertEqual(DEFAULT_COMMIT_CODE, "92206dc")
    self.assertEqual(APP_VERSION, "1.29.0")

  def test_resolve_commit_code_lives_in_vcs_adapter(self):
    resolved = resolve_commit_code()
    self.assertIsInstance(resolved, str)
    self.assertTrue(len(resolved) >= 7)

  def test_app_module_import_pure_no_subprocess(self):
    from unittest.mock import patch
    with patch("subprocess.check_output", side_effect=AssertionError("subprocess called at import")):
      import app.main
      self.assertEqual(app.main.app.state.commit_code, DEFAULT_COMMIT_CODE)

  def test_jinja_templates_globals_contain_commit_code(self):
    from app.web.templating import templates
    self.assertIn("commit_code", templates.env.globals)
    self.assertIsInstance(templates.env.globals["commit_code"], str)
    self.assertTrue(len(templates.env.globals["commit_code"]) >= 7)


if __name__ == "__main__":
  unittest.main()
