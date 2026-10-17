import json
import unittest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
import httpx

from app.adapters.discord import DiscordAdapter
from app.core.models import (
    AppConfigModel,
    PowerState,
    ServerModel,
    ServerRuntimeState,
    ServerStatusDTO,
    ServerUpdateStatus,
    SteamPatchNotes,
)
from app.main import app
from app.services.runtime_state import RuntimeStateStore
from app.services.server_service import ServerService
from app.services.status_service import StatusAggregationService
from app.web.schemas import (
    SettingsUpdateDTO,
    SimulateBuildRequest,
    SingleServerSaveRequest,
    SyncNameRequest,
)


class TestServerUpdateStatusEnum(unittest.TestCase):

  def test_server_update_status_values_and_identity(self):
    self.assertEqual(ServerUpdateStatus.UP_TO_DATE, "Up to date")
    self.assertEqual(ServerUpdateStatus.UPDATE_AVAILABLE, "Update Available")
    self.assertEqual(ServerUpdateStatus.COUNTDOWN_ACTIVE, "Update Available (Countdown Active)")
    self.assertEqual(ServerUpdateStatus.RESTART_DISPATCHED, "Restart dispatched — waiting for build update")
    self.assertEqual(ServerUpdateStatus.IDLE, "Idle")
    self.assertEqual(ServerUpdateStatus.ERROR, "Error")

    self.assertEqual(
        {s.value for s in ServerUpdateStatus},
        {
            "Up to date",
            "Update Available",
            "Update Available (Countdown Active)",
            "Restart dispatched — waiting for build update",
            "Idle",
            "Error",
        },
    )

  def test_server_update_status_string_inheritance(self):
    self.assertIsInstance(ServerUpdateStatus.UP_TO_DATE, str)
    self.assertIsInstance(ServerUpdateStatus.UPDATE_AVAILABLE, str)
    self.assertEqual(f"{ServerUpdateStatus.UP_TO_DATE}", "Up to date")
    self.assertEqual(str(ServerUpdateStatus.COUNTDOWN_ACTIVE), "Update Available (Countdown Active)")

  def test_server_update_status_from_str_normalization(self):
    # Direct match (case insensitive)
    self.assertIs(ServerUpdateStatus.from_str(ServerUpdateStatus.UP_TO_DATE), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("Up to date"), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("UP TO DATE"), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("  up to date  "), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("Update Available"), ServerUpdateStatus.UPDATE_AVAILABLE)
    self.assertIs(ServerUpdateStatus.from_str("Idle"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Error"), ServerUpdateStatus.ERROR)

    # Partial / Legacy fuzzy matches
    self.assertIs(ServerUpdateStatus.from_str("Manual offline — countdown cancelled"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Countdown cancelled (restart requested)"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Test mode disabled — countdown cancelled"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Update Available — Countdown Started"), ServerUpdateStatus.COUNTDOWN_ACTIVE)
    self.assertIs(ServerUpdateStatus.from_str("Restarting server via Pterodactyl API..."), ServerUpdateStatus.RESTART_DISPATCHED)
    self.assertIs(ServerUpdateStatus.from_str("waiting for build update"), ServerUpdateStatus.RESTART_DISPATCHED)
    self.assertIs(ServerUpdateStatus.from_str("Error: Failed to fetch build"), ServerUpdateStatus.ERROR)
    self.assertIs(ServerUpdateStatus.from_str("Connection failed"), ServerUpdateStatus.ERROR)

    # Empty and unknown fallback to IDLE
    self.assertIs(ServerUpdateStatus.from_str(None), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str(""), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("unknown_xyz"), ServerUpdateStatus.IDLE)

  def test_server_status_dto_accepts_enum_and_str(self):
    dto = ServerStatusDTO(
        idx=0,
        server_id="srv1",
        name="Server 1",
        power_state=PowerState.RUNNING,
        current_build="100",
        latest_build="200",
        last_status=ServerUpdateStatus.UPDATE_AVAILABLE,
        target_timestamp=0.0,
        remaining_seconds=0,
        is_updating=True,
    )
    self.assertEqual(dto.last_status, ServerUpdateStatus.UPDATE_AVAILABLE)
    self.assertEqual(dto.last_status, "Update Available")

    dumped = dto.model_dump()
    self.assertEqual(dumped["last_status"], "Update Available")


class TestSteamPatchNotesDTO(unittest.IsolatedAsyncioTestCase):

  def test_steam_patch_notes_instantiation_and_embed_generation(self):
    notes = SteamPatchNotes(
        title="Major Game Update 2.0",
        content="Bug fixes and performance improvements",
        url="https://steamcommunity.com/news/123",
        image_url="https://steam.cdn/banner.png",
        posted_at="1700000000",
    )
    self.assertEqual(notes.title, "Major Game Update 2.0")
    self.assertEqual(notes.content, "Bug fixes and performance improvements")
    self.assertEqual(notes.url, "https://steamcommunity.com/news/123")
    self.assertEqual(notes.image_url, "https://steam.cdn/banner.png")
    self.assertEqual(notes.posted_at, "1700000000")

    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertEqual(embed["title"], "📜 Major Game Update 2.0")
    self.assertEqual(embed["url"], "https://steamcommunity.com/news/123")
    self.assertEqual(embed["description"], "Bug fixes and performance improvements")
    self.assertEqual(embed["color"], 0x1B2838)
    self.assertEqual(embed["footer"]["text"], "Steam Official Announcement")
    self.assertEqual(embed["image"]["url"], "https://steam.cdn/banner.png")

  def test_steam_patch_notes_to_embed_without_image(self):
    notes = SteamPatchNotes(
        title="Minor Hotfix",
        content="Crash fix",
        url="https://steamcommunity.com/news/456",
        image_url=None,
    )
    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertNotIn("image", embed)

  def test_steam_patch_notes_pure_dto_without_presentation_logic(self):
    notes = SteamPatchNotes(
        title="Update v1",
        content="Changes",
        url="https://steamcommunity.com/news/789",
    )
    # Pure domain DTO: no presentation methods or dict subscripting
    self.assertFalse(hasattr(notes, "to_embed"))
    self.assertFalse(hasattr(notes, "get"))
    with self.assertRaises(TypeError):
      _ = notes["title"]

  def test_discord_adapter_create_patchnotes_embed(self):
    notes = SteamPatchNotes(
        title="Update 3.0",
        content="New features",
        url="https://steamcommunity.com/news/999",
    )
    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertEqual(embed["title"], "📜 Update 3.0")
    self.assertEqual(embed["url"], "https://steamcommunity.com/news/999")

    # Dict pass-through
    raw_dict = {"title": "Raw Embed", "color": 123}
    self.assertEqual(DiscordAdapter.create_patchnotes_embed(raw_dict), raw_dict)

  async def test_discord_adapter_send_notification_with_steam_patch_notes(self):
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = MagicMock(is_success=True, status_code=204)
    adapter = DiscordAdapter(mock_client)

    notes = SteamPatchNotes(
        title="Update v2.1",
        content="Details",
        url="https://steamcommunity.com/news/222",
    )
    await adapter.send_notification("http://discord.webhook", "Alert", embed=notes)
    mock_client.post.assert_called_once()
    payload = mock_client.post.call_args[1]["json"]
    self.assertEqual(payload["content"], "Alert")
    self.assertEqual(payload["embeds"][0]["title"], "📜 Update v2.1")


class TestRuntimeStateStoreLifecycleSync(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.store = RuntimeStateStore()

  def test_remove_and_delete_server_state(self):
    self.store.update_server_state("srv1", current_build="100", latest_build="200")
    self.store.update_server_state("srv2", current_build="300", latest_build="400")
    self.assertIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv2", self.store.get_all_server_states())

    self.store.remove_server_state("srv1")
    self.assertNotIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv2", self.store.get_all_server_states())

    self.store.delete_server_state("srv2")
    self.assertNotIn("srv2", self.store.get_all_server_states())

  def test_server_service_save_settings_synchronizes_runtime_state(self):
    repo = MagicMock()
    repo.load.return_value = AppConfigModel(servers=[ServerModel(server_id="srv1")])
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    # Seed initial state for srv1 and an old srv_deprecated
    self.store.update_server_state("srv1", current_build="100")
    self.store.update_server_state("srv_deprecated", current_build="999")
    self.assertIn("srv1", self.store.get_all_server_states())
    self.assertIn("srv_deprecated", self.store.get_all_server_states())

    # Save settings replacing srv_deprecated with srv2
    new_settings = SettingsUpdateDTO(
        servers=[
            ServerModel(server_id="srv1", name="Server 1"),
            ServerModel(server_id="srv2", name="Server 2"),
        ]
    )
    service.save_settings(new_settings)

    all_states = self.store.get_all_server_states()
    self.assertIn("srv1", all_states)
    self.assertIn("srv2", all_states)
    self.assertNotIn("srv_deprecated", all_states)

  def test_server_service_delete_server_cleans_runtime_state(self):
    repo = MagicMock()
    srv1 = ServerModel(server_id="srv1", name="Server 1")
    srv2 = ServerModel(server_id="srv2", name="Server 2")
    cfg = AppConfigModel(servers=[srv1, srv2])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("srv1", current_build="100")
    self.store.update_server_state("srv2", current_build="200")

    settings = SettingsUpdateDTO(servers=[srv1, srv2])
    service.delete_server("srv1", settings)

    all_states = self.store.get_all_server_states()
    self.assertNotIn("srv1", all_states)
    self.assertIn("srv2", all_states)

  async def test_server_service_save_single_server_updates_id_in_runtime_state(self):
    repo = MagicMock()
    srv = ServerModel(server_id="old_srv", name="Initial")
    cfg = AppConfigModel(servers=[srv])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("old_srv", current_build="555")

    await service.save_single_server("old_srv", {"server_id": "new_srv", "name": "Renamed"})

    all_states = self.store.get_all_server_states()
    self.assertNotIn("old_srv", all_states)
    self.assertIn("new_srv", all_states)
    self.assertEqual(all_states["new_srv"].current_build, "555")

  def test_runtime_state_store_rename_server_state(self):
    self.store.update_server_state("srv-a", current_build="100", latest_build="200", last_status=ServerUpdateStatus.UP_TO_DATE)
    renamed = self.store.rename_server_state("srv-a", "srv-b")
    self.assertIsNotNone(renamed)
    self.assertEqual(renamed.server_id, "srv-b")
    self.assertEqual(renamed.current_build, "100")
    self.assertEqual(renamed.latest_build, "200")
    self.assertEqual(renamed.last_status, ServerUpdateStatus.UP_TO_DATE)

    states = self.store.get_all_server_states()
    self.assertNotIn("srv-a", states)
    self.assertIn("srv-b", states)

  async def test_server_service_sync_server_name_migrates_runtime_state(self):
    repo = MagicMock()
    srv = ServerModel(server_id="srv-initial", name="Old Box")
    cfg = AppConfigModel(panel_url="http://panel.test", api_key="testkey", servers=[srv])
    repo.load.return_value = cfg
    ptero = AsyncMock()
    ptero.get_server_name.return_value = MagicMock(name="Synced Box")
    steam = AsyncMock()
    sim_store = MagicMock()
    countdown = MagicMock()

    service = ServerService(
        repository=repo,
        ptero=ptero,
        steam=steam,
        simulator_store=sim_store,
        countdown=countdown,
        runtime_state=self.store,
    )

    self.store.update_server_state("srv-initial", current_build="777", latest_build="888")
    await service.sync_server_name("srv-initial", server_id_override="srv-overridden")

    states = self.store.get_all_server_states()
    self.assertNotIn("srv-initial", states)
    self.assertIn("srv-overridden", states)
    self.assertEqual(states["srv-overridden"].current_build, "777")
    self.assertEqual(states["srv-overridden"].latest_build, "888")

  def test_server_service_add_server_synchronizes_runtime_state(self):
    repo = MagicMock()
    cfg = AppConfigModel(servers=[ServerModel(server_id="srv-keep")])
    repo.load.return_value = cfg
    service = ServerService(
        repository=repo,
        ptero=AsyncMock(),
        steam=AsyncMock(),
        simulator_store=MagicMock(),
        countdown=MagicMock(),
        runtime_state=self.store,
    )

    self.store.update_server_state("srv-keep", current_build="111")
    self.store.update_server_state("srv-stale", current_build="999")

    new_settings = SettingsUpdateDTO(servers=[ServerModel(server_id="srv-keep")])
    service.add_server(new_settings)

    states = self.store.get_all_server_states()
    self.assertIn("srv-keep", states)
    self.assertNotIn("srv-stale", states)


class TestTypedRouteSchemas(unittest.TestCase):

  def test_simulate_build_request_schema(self):
    req = SimulateBuildRequest(build_id="12345")
    self.assertEqual(req.build_id, "12345")
    self.assertIsNone(req.server_id)
    self.assertEqual(req.server_idx, 0)

    req2 = SimulateBuildRequest(build_id="67890", server_id="srv-alpha", server_idx=1)
    self.assertEqual(req2.build_id, "67890")
    self.assertEqual(req2.server_id, "srv-alpha")
    self.assertEqual(req2.server_idx, 1)

  def test_sync_name_request_schema(self):
    req = SyncNameRequest(server_id="srv-100")
    self.assertEqual(req.server_id, "srv-100")

  def test_single_server_save_request_schema(self):
    req = SingleServerSaveRequest(
        name="Valheim Box",
        server_id="srv-v",
        app_id="896660",
        manifest_path="steamapps/manifest.acf",
        query_port_offset=1,
    )
    self.assertEqual(req.name, "Valheim Box")
    self.assertEqual(req.server_id, "srv-v")
    self.assertEqual(req.app_id, "896660")
    self.assertEqual(req.manifest_path, "steamapps/manifest.acf")
    self.assertEqual(req.query_port_offset, 1)


class TestTypedRouteEndpoints(unittest.TestCase):

  def setUp(self):
    self.client = TestClient(app, raise_server_exceptions=True)
    self.service = MagicMock()
    app.state.server_service = self.service

  def test_simulate_build_typed_endpoint_success(self):
    self.service.trigger_simulated_build = AsyncMock(return_value="srv-alpha")
    res = self.client.post(
        "/api/test/simulate-build",
        json={"build_id": "88888", "server_id": "srv-alpha"},
    )
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("build_id"), "88888")
    self.service.trigger_simulated_build.assert_called_once_with("srv-alpha", "88888")

  def test_simulate_build_typed_endpoint_validation_error(self):
    # Missing required build_id
    res = self.client.post("/api/test/simulate-build", json={"server_id": "srv-alpha"})
    self.assertEqual(res.status_code, 422)

  def test_sync_name_typed_endpoint_success(self):
    self.service.sync_server_name = AsyncMock(return_value="Synced Box")
    res = self.client.post(
        "/api/servers/srv-beta/sync-name",
        json={"server_id": "srv-beta"},
    )
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("name"), "Synced Box")
    self.service.sync_server_name.assert_called_once_with("srv-beta", server_id_override="srv-beta")

  def test_save_single_server_typed_endpoint_success(self):
    saved_srv = ServerModel(
        name="Updated Valheim",
        server_id="srv-v",
        app_id="896660",
        manifest_path="steamapps/appmanifest_896660.acf",
        query_port_offset=2,
    )
    self.service.save_single_server = AsyncMock(return_value=saved_srv)

    payload = {
        "name": "Updated Valheim",
        "server_id": "srv-v",
        "app_id": "896660",
        "manifest_path": "steamapps/appmanifest_896660.acf",
        "query_port_offset": 2,
    }
    res = self.client.post("/api/servers/srv-v/save", json=payload)
    self.assertEqual(res.status_code, 200)
    data = res.json()
    self.assertEqual(data.get("status"), "ok")
    self.assertEqual(data.get("server", {}).get("name"), "Updated Valheim")
    self.assertEqual(data.get("server", {}).get("query_port_offset"), 2)


class TestTemplateRenderingAndDirectDecoupling(unittest.TestCase):

  def test_global_status_template_renders_live_last_check(self):
    from app.web.templating import templates
    cfg = AppConfigModel()
    # cfg._last_check is 'Never' by default
    rendered = templates.get_template("components/_global_status.html").render({
        "cfg": cfg,
        "last_check": "2026-10-16 19:30:00",
    })
    self.assertIn("2026-10-16 19:30:00", rendered)
    self.assertNotIn(">Never<", rendered)

  def test_server_card_template_renders_builds_from_runtime_states(self):
    from app.web.templating import templates
    srv = ServerModel(server_id="srv-val", name="Valheim")
    cfg = AppConfigModel(servers=[srv])
    runtime_states = {
        "srv-val": ServerRuntimeState(
            server_id="srv-val",
            current_build="999000",
            latest_build="999000",
            last_status=ServerUpdateStatus.UP_TO_DATE,
        )
    }
    rendered = templates.get_template("components/_server_card.html").render({
        "cfg": cfg,
        "srv": srv,
        "idx": 0,
        "srv_id": "srv-val",
        "runtime_states": runtime_states,
    })
    self.assertIn("Build:", rendered)
    self.assertIn("999000", rendered)

  def test_discord_adapter_create_patchnotes_embed_direct_construction(self):
    notes = SteamPatchNotes(
        title="Patch 0.219",
        content="Optimizations applied.",
        url="https://steamcommunity.com/news/123",
        image_url="https://steam.cdn/banner.png",
    )
    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertEqual(embed["title"], "📜 Patch 0.219")
    self.assertEqual(embed["url"], "https://steamcommunity.com/news/123")
    self.assertEqual(embed["description"], "Optimizations applied.")
    self.assertEqual(embed["color"], 0x1B2838)
    self.assertEqual(embed["footer"]["text"], "Steam Official Announcement")
    self.assertEqual(embed["image"]["url"], "https://steam.cdn/banner.png")


if __name__ == "__main__":
  unittest.main()
