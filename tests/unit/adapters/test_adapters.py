import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from markupsafe import Markup
import httpx

from app.adapters.a2s import A2SAdapter, A2S_INFO_REQUEST
from app.adapters.discord import DiscordAdapter
from app.adapters.power_tracker import PowerStateTracker
from app.adapters.pterodactyl import PterodactylAdapter
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.core.config import TIMING_CONFIG
from app.core.exceptions import NotificationError
from app.core.models import PlayerMetrics, PowerSignal, PowerState, SteamPatchNotes
from app.core.protocols import NotificationGateway, SteamGateway
from app.web.filters import discord_markdown


class TestPowerStateTracker(unittest.TestCase):

  def setUp(self):
    self.tracker = PowerStateTracker()

  def test_default_state_is_unknown(self):
    self.assertIsNone(self.tracker.get_valid_cache("srv1"))
    state = self.tracker.filter_state("srv1", "unknown")
    self.assertEqual(state, "unknown")

  def test_register_signal_start_and_restart(self):
    now = time.time()
    with patch("time.time", return_value=now):
      state = self.tracker.register_signal("srv1", "start")
      self.assertEqual(state, "starting")
      self.assertEqual(self.tracker.get_valid_cache("srv1"), "starting")

      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["starting_since"], now)
      self.assertEqual(entry["startup_grace_until"], now + TIMING_CONFIG.startup_grace_duration)
      self.assertEqual(entry["restart_lockout_until"], 0.0)

    # Restart signal sets restart lockout
    with patch("time.time", return_value=now + 1.0):
      state = self.tracker.register_signal("srv1", "restart")
      self.assertEqual(state, "starting")
      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["restart_lockout_until"], now + 1.0 + TIMING_CONFIG.restart_lockout_duration)

  def test_register_signal_stop_and_kill(self):
    now = time.time()
    with patch("time.time", return_value=now):
      state = self.tracker.register_signal("srv1", "stop")
      self.assertEqual(state, "stopping")
      self.assertEqual(self.tracker.get_valid_cache("srv1"), "stopping")

      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["stopping_since"], now)
      self.assertFalse(entry["stopped_during_start"])

    # If stopped while container was starting
    self.tracker._get_entry("srv1")["smoothed_state"] = "starting"
    with patch("time.time", return_value=now + 2.0):
      self.tracker.register_signal("srv1", "kill")
      entry = self.tracker._get_entry("srv1")
      self.assertTrue(entry["stopped_during_start"])

  def test_restart_lockout_suppresses_stale_running_reports(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "restart")

    # During lockout, raw "running" report is suppressed and smoothed to "starting"
    with patch("time.time", return_value=now + 5.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "starting")

    # Once lockout expires, raw "running" is accepted
    with patch("time.time", return_value=now + 20.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_stopping_transitions_to_offline_cleanly(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # While shutting down, container still reports stopping
    with patch("time.time", return_value=now + 5.0):
      filtered = self.tracker.filter_state("srv1", "stopping")
      self.assertEqual(filtered, "stopping")

    # Once Wings reports offline/stopped, transitions to offline
    with patch("time.time", return_value=now + 10.0):
      filtered = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(filtered, "offline")

  def test_aborted_start_stop_recovery_edge_case(self):
    now = time.time()
    self.tracker._get_entry("srv1")["smoothed_state"] = "starting"
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # Before aborted start grace (8s), still reports stopping
    with patch("time.time", return_value=now + 4.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "stopping")

    # After aborted start grace (8s), server ignored stop and continues running
    with patch("time.time", return_value=now + 12.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_stopping_timeout_recovery_after_max_duration(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # Exceeding MAX_STOPPING_DURATION (45s) while container remains running recovers to running
    with patch("time.time", return_value=now + 50.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_startup_grace_period_suppresses_spurious_offline_reports(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "start")

    # Within startup grace (30s), raw offline is smoothed to starting
    with patch("time.time", return_value=now + 10.0):
      filtered = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(filtered, "starting")

  def test_offline_confirmation_threshold(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "start")

    # Fast forward past startup grace (35s)
    with patch("time.time", return_value=now + 35.0):
      # 1st offline -> starting
      f1 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f1, "starting")
      # 2nd offline -> starting
      f2 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f2, "starting")
      # 3rd offline -> reached threshold (3) -> offline confirmed
      f3 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f3, "offline")

  def test_wings_running_instant_transition_and_pop_just_started(self):
    self.tracker.register_signal("srv1", "start")
    self.assertFalse(self.tracker.pop_just_started("srv1"))

    filtered = self.tracker.filter_state("srv1", "running")
    self.assertEqual(filtered, "running")
    # Instant transition to Online triggers just_started
    self.assertTrue(self.tracker.pop_just_started("srv1"))
    # Second check returns False (consumed)
    self.assertFalse(self.tracker.pop_just_started("srv1"))

  def test_invalidate_cache(self):
    self.tracker.register_signal("srv1", "start")
    self.assertIsNotNone(self.tracker.get_valid_cache("srv1"))

    # Invalidate single server
    self.tracker.invalidate("srv1")
    self.assertIsNone(self.tracker.get_valid_cache("srv1"))

    # Invalidate all servers
    self.tracker.register_signal("srv2", "start")
    self.assertIsNotNone(self.tracker.get_valid_cache("srv2"))
    self.tracker.invalidate()
    self.assertIsNone(self.tracker.get_valid_cache("srv2"))

  def test_power_state_tracker_strenum_types(self):
    # register_signal with PowerSignal enum
    state = self.tracker.register_signal("srv1", PowerSignal.START)
    self.assertIsInstance(state, PowerState)
    self.assertIs(state, PowerState.STARTING)

    # get_valid_cache returns PowerState enum
    cached = self.tracker.get_valid_cache("srv1")
    self.assertIsInstance(cached, PowerState)
    self.assertIs(cached, PowerState.STARTING)

    # filter_state with PowerState enum
    filtered = self.tracker.filter_state("srv1", PowerState.RUNNING)
    self.assertIsInstance(filtered, PowerState)
    self.assertIs(filtered, PowerState.RUNNING)

    # filter_state with Wings "stopped" string maps to PowerState.OFFLINE
    self.tracker.register_signal("srv1", PowerSignal.STOP)
    filtered_offline = self.tracker.filter_state("srv1", "stopped")
    self.assertIsInstance(filtered_offline, PowerState)
    self.assertIs(filtered_offline, PowerState.OFFLINE)

    # filter_state with unexpected string maps to PowerState.UNKNOWN
    unknown_state = self.tracker.filter_state("new_server", "crashed_or_gibberish")
    self.assertIsInstance(unknown_state, PowerState)
    self.assertIs(unknown_state, PowerState.UNKNOWN)

  def test_power_state_tracker_rapid_consecutive_transitions(self):
    # Rapid sequence START -> STOP -> START within grace windows
    s1 = self.tracker.register_signal("srv_rapid", PowerSignal.START)
    self.assertIs(s1, PowerState.STARTING)

    s2 = self.tracker.register_signal("srv_rapid", PowerSignal.STOP)
    self.assertIs(s2, PowerState.STOPPING)
    self.assertTrue(self.tracker._get_entry("srv_rapid")["stopped_during_start"])

    s3 = self.tracker.register_signal("srv_rapid", PowerSignal.START)
    self.assertIs(s3, PowerState.STARTING)
    self.assertFalse(self.tracker._get_entry("srv_rapid")["stopped_during_start"])

    # Wings reports running -> transitions immediately to RUNNING with just_started flag
    f = self.tracker.filter_state("srv_rapid", PowerState.RUNNING)
    self.assertIs(f, PowerState.RUNNING)
    self.assertTrue(self.tracker.pop_just_started("srv_rapid"))

  def test_power_state_tracker_case_insensitivity_and_strings(self):
    # Uppercase string signals and statuses
    s_start = self.tracker.register_signal("srv_case", "START")
    self.assertIs(s_start, PowerState.STARTING)

    s_stop = self.tracker.register_signal("srv_case", "STOP")
    self.assertIs(s_stop, PowerState.STOPPING)

    # In STOPPING state, STOPPED transitions cleanly to OFFLINE
    f_stopped = self.tracker.filter_state("srv_case", "STOPPED")
    self.assertIs(f_stopped, PowerState.OFFLINE)

    s_kill = self.tracker.register_signal("srv_case", "KILL")
    self.assertIs(s_kill, PowerState.STOPPING)

    # Invalid signal string leaves state unchanged
    s_bad = self.tracker.register_signal("srv_case", "invalid_action")
    self.assertIs(s_bad, PowerState.STOPPING)


class TestSteamAdapterSanitization(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = SteamAdapter(self.mock_client)

  def test_clean_content_delegation_and_backward_compatibility(self):
    sample = "[b]Update[/b]\nDetails here"
    # Instance method call
    cleaned, img = self.adapter._clean_content(sample)
    self.assertEqual(cleaned, "**Update**\nDetails here")
    self.assertIsNone(img)

    # Class-level static call
    cleaned_cls, img_cls = SteamAdapter._clean_content(sample)
    self.assertEqual(cleaned_cls, "**Update**\nDetails here")
    self.assertIsNone(img_cls)

    # Default / None handling
    empty_cleaned, empty_img = self.adapter._clean_content()
    self.assertEqual(empty_cleaned, "")
    self.assertIsNone(empty_img)

  async def test_fetch_patchnotes_parses_feed(self):
    feed_response = {
        "appnews": {
            "newsitems": [
                {
                    "title": "Version 1.5 Update",
                    "url": "https://steamcommunity.com/news/123",
                    "contents": "[img]https://clan.cloudflare.steamstatic.com/banner.png[/img]\n[b]Patch notes[/b]",
                    "date": 1700000000,
                }
            ]
        }
    }
    self.mock_client.get.return_value = MagicMock(status_code=200, json=lambda: feed_response)

    notes = await self.adapter.fetch_patchnotes(896660)
    self.assertIsNotNone(notes)
    self.assertIsInstance(notes, SteamPatchNotes)
    self.assertEqual(notes.title, "Version 1.5 Update")
    self.assertEqual(notes.url, "https://steamcommunity.com/news/123")
    self.assertIn("**Patch notes**", notes.content)
    self.assertEqual(notes.image_url, "https://clan.cloudflare.steamstatic.com/banner.png")

    # Verify to_embed() generation
    embed = notes.to_embed()
    self.assertEqual(embed["title"], "📜 Version 1.5 Update")
    self.assertEqual(embed["url"], "https://steamcommunity.com/news/123")
    self.assertIn("**Patch notes**", embed["description"])
    self.assertEqual(embed["image"]["url"], "https://clan.cloudflare.steamstatic.com/banner.png")
    self.assertEqual(embed["color"], 0x1B2838)

    # Verify dict-like access backward-compatibility
    self.assertEqual(notes["title"], "📜 Version 1.5 Update")
    self.assertEqual(notes["url"], "https://steamcommunity.com/news/123")


class TestA2SAdapterDatagram(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.adapter = A2SAdapter()

  def test_parse_a2s_response_valid_info_packet(self):
    # Construct synthetic A2S_INFO packet
    data = (
        b"\xff\xff\xff\xff\x49"  # Header (0xFFFFFFFF) + Type (0x49)
        b"\x11"                  # Protocol version 17
        b"Valheim Dedicated Server\x00"  # Name
        b"Dedicated\x00"                 # Map
        b"valheim\x00"                   # Folder
        b"Valheim\x00"                   # Game
        b"\x88\x13"                      # Steam AppID (5000)
        + bytes([8, 64])                 # Players (8), Max Players (64)
    )
    parsed = self.adapter._parse_a2s_response(data)
    self.assertIsNotNone(parsed)
    self.assertEqual(parsed["players"], 8)
    self.assertEqual(parsed["max_players"], 64)

  def test_parse_a2s_response_challenge_packet(self):
    data = b"\xff\xff\xff\xff\x41\x11\x22\x33\x44"
    parsed = self.adapter._parse_a2s_response(data)
    self.assertIsNotNone(parsed)
    self.assertEqual(parsed["challenge"], b"\x11\x22\x33\x44")

  def test_parse_a2s_response_invalid_packets(self):
    # Too short
    self.assertIsNone(self.adapter._parse_a2s_response(b"\x00\x00"))
    # Wrong magic header
    self.assertIsNone(self.adapter._parse_a2s_response(b"\x01\x02\x03\x04\x49"))
    # Unknown type byte
    self.assertIsNone(self.adapter._parse_a2s_response(b"\xff\xff\xff\xff\x99"))

  async def test_get_player_count_invalid_arguments_returns_none(self):
    res = await self.adapter.get_player_count("", 0)
    self.assertEqual(res, PlayerMetrics(None, None))
    res2 = await self.adapter.get_player_count("127.0.0.1", -5)
    self.assertEqual(res2, PlayerMetrics(None, None))

  async def test_get_player_count_with_challenge_resend(self):
    mock_transport = MagicMock()
    mock_protocol = MagicMock()
    mock_protocol.queue = asyncio.Queue()

    # 1st response: Challenge request (0x41)
    mock_protocol.queue.put_nowait(b"\xff\xff\xff\xff\x41\xaa\xbb\xcc\xdd")

    # 2nd response: Valid info response (0x49) with 15 players of 32
    info_packet = (
        b"\xff\xff\xff\xff\x49\x11"
        b"My Palworld\x00"
        b"World\x00"
        b"Pal\x00"
        b"Palworld\x00"
        b"\x00\x00"
        + bytes([15, 32])
    )
    mock_protocol.queue.put_nowait(info_packet)

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new=AsyncMock(return_value=(mock_transport, mock_protocol)),
    ):
      metrics = await self.adapter.get_player_count("1.2.3.4", 27015)
      self.assertEqual(metrics.current, 15)
      self.assertEqual(metrics.max, 32)

      # Verify challenge resend occurred
      self.assertEqual(mock_transport.sendto.call_count, 2)
      expected_second_call = A2S_INFO_REQUEST + b"\xaa\xbb\xcc\xdd"
      mock_transport.sendto.assert_called_with(expected_second_call)


class TestDiscordMarkdownFilter(unittest.TestCase):

  def test_empty_and_none_text(self):
    self.assertEqual(discord_markdown(""), Markup(""))
    self.assertEqual(discord_markdown(None), Markup(""))

  def test_raw_html_is_escaped(self):
    text = "<script>alert('pwned')</script> & <b>test</b>"
    result = str(discord_markdown(text))
    self.assertNotIn("<script>", result)
    self.assertNotIn("<b>", result)
    self.assertIn("&lt;script&gt;", result)
    self.assertIn("&lt;b&gt;test&lt;/b&gt;", result)

  def test_markdown_bold_and_italic(self):
    text = "**bold text** and *italic text*"
    result = str(discord_markdown(text))
    self.assertIn('<strong class="font-semibold text-white">bold text</strong>', result)
    self.assertIn("<em>italic text</em>", result)

  def test_markdown_underline_and_strikethrough(self):
    text = "__underlined__ and ~~struck~~"
    result = str(discord_markdown(text))
    self.assertIn('<span class="underline">underlined</span>', result)
    self.assertIn('<span class="line-through text-gray-400">struck</span>', result)

  def test_markdown_links(self):
    text = "Visit [Valheim Discord](https://discord.gg/valheim) for help."
    result = str(discord_markdown(text))
    self.assertIn(
        '<a href="https://discord.gg/valheim" target="_blank" rel="noopener noreferrer"'
        ' class="text-blue-400 hover:underline break-all">Valheim Discord</a>',
        result,
    )

  def test_markdown_headings(self):
    text = "### Patch 0.218 Notes"
    result = str(discord_markdown(text))
    self.assertIn('<h4 class="font-bold text-white text-sm mt-3 mb-1">Patch 0.218 Notes</h4>', result)

  def test_markdown_bullet_points(self):
    text = "* First fix\n• Second fix"
    result = str(discord_markdown(text))
    self.assertIn('<div class="flex items-start gap-2 ml-1 my-0.5"><span class="text-gray-400 select-none">•</span><span class="flex-1">First fix</span></div>', result)
    self.assertIn('<div class="flex items-start gap-2 ml-1 my-0.5"><span class="text-gray-400 select-none">•</span><span class="flex-1">Second fix</span></div>', result)


class TestPterodactylAdapterDetailsDetection(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = PterodactylAdapter(self.mock_client)

  async def test_detect_server_details_from_startup_variables(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [
                {
                    "attributes": {
                        "env_variable": "APP_ID",
                        "server_value": "2230650",
                    }
                }
            ],
            "meta": {"startup_command": "./server"},
        }
      elif url.endswith("/files/list"):
        resp.json.return_value = {"data": []}
      else:
        resp.json.return_value = {
            "attributes": {"name": "My Enshrouded Dedicated Server"}
        }
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-1"
    )
    self.assertEqual(details["app_id"], "2230650")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2230650.acf")
    self.assertEqual(details["name"], "My Enshrouded Dedicated Server")

  async def test_detect_server_details_from_manifest_file(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_2394010.acf"}}
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Palworld Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-2"
    )
    self.assertEqual(details["app_id"], "2394010")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2394010.acf")
    self.assertEqual(details["name"], "Palworld Server")

  async def test_detect_server_details_from_server_name(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {"data": []}
      else:
        resp.json.return_value = {"attributes": {"name": "Official Valheim Realm"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-3"
    )
    self.assertEqual(details["app_id"], "896660")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_896660.acf")
    self.assertEqual(details["name"], "Official Valheim Realm")

  async def test_get_local_build_empty_manifest_or_server_id_returns_clean_error(self):
    build, err = await self.adapter.get_local_build(
        "http://panel.test", "key", "", ""
    )
    self.assertIsNone(build)
    self.assertIn("not configured", err)

  async def test_detect_server_details_ignores_1007_manifest_and_picks_game_manifest(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {"data": [], "meta": {"startup_command": ""}}
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_1007.acf"}},
                {"attributes": {"name": "appmanifest_2278520.acf"}},
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Enshrouded Realm"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-enshrouded"
    )
    self.assertEqual(details["app_id"], "2278520")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2278520.acf")

  async def test_detect_server_details_from_startup_command_flag(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [],
            "meta": {
                "startup_command": "steamcmd +force_install_dir /home/container +login anonymous +app_update 2278520 validate +quit"
            },
        }
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [{"attributes": {"name": "appmanifest_1007.acf"}}]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Enshrouded Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-enshrouded"
    )
    self.assertEqual(details["app_id"], "2278520")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_2278520.acf")

  async def test_detect_server_details_preserves_detected_appid_when_1007_is_in_files(self):
    def fake_get(url, **kwargs):
      resp = MagicMock()
      resp.status_code = 200
      if url.endswith("/startup"):
        resp.json.return_value = {
            "data": [
                {"attributes": {"env_variable": "STEAM_APPID", "server_value": "896660"}}
            ],
            "meta": {"startup_command": ""},
        }
      elif "/files/list" in url:
        resp.json.return_value = {
            "data": [
                {"attributes": {"name": "appmanifest_1007.acf"}},
                {"attributes": {"name": "appmanifest_896660.acf"}},
            ]
        }
      else:
        resp.json.return_value = {"attributes": {"name": "Valheim Server"}}
      return resp

    self.mock_client.get = AsyncMock(side_effect=fake_get)

    details = await self.adapter.detect_server_details(
        "http://panel.test", "key", "srv-valheim"
    )
    self.assertEqual(details["app_id"], "896660")
    self.assertEqual(details["manifest_path"], "steamapps/appmanifest_896660.acf")


class TestSteamAdapterSearch(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = SteamAdapter(self.mock_client)

  async def test_search_empty_query_returns_popular_catalog(self):
    results = await self.adapter.search_games("")
    self.assertGreaterEqual(len(results), 5)
    app_ids = [r["app_id"] for r in results]
    self.assertIn("2278520", app_ids)  # Enshrouded
    self.assertIn("896660", app_ids)   # Valheim

  async def test_search_games_from_catalog(self):
    results = await self.adapter.search_games("enshrouded")
    self.assertGreaterEqual(len(results), 1)
    enshrouded = next(r for r in results if r["app_id"] == "2278520")
    self.assertIn("Enshrouded", enshrouded["name"])
    self.assertEqual(enshrouded["type"], "dedicated_server")

  async def test_search_games_store_api_fallback_and_mapping(self):
    store_response = {
        "total": 1,
        "items": [
            {"id": 108600, "name": "Project Zomboid"}
        ]
    }
    self.mock_client.get = AsyncMock(
        return_value=MagicMock(status_code=200, json=lambda: store_response)
    )

    results = await self.adapter.search_games("zomboid")
    app_ids = [r["app_id"] for r in results]
    self.assertIn("380870", app_ids)  # Project Zomboid Dedicated Server


class TestSimulatedSteamAdapter(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.real_steam = AsyncMock()
    self.store = MagicMock()
    self.repo = MagicMock()
    self.adapter = SimulatedSteamAdapter(
        real_steam=self.real_steam,
        simulator_store=self.store,
        repository=self.repo,
    )

  async def test_search_games_delegates_to_real_steam(self):
    self.real_steam.search_games.return_value = [
        {"app_id": "2278520", "name": "Enshrouded"}
    ]
    results = await self.adapter.search_games("enshrouded")
    self.assertEqual(results, [{"app_id": "2278520", "name": "Enshrouded"}])
    self.real_steam.search_games.assert_called_once_with("enshrouded")

  def test_simulated_steam_adapter_conforms_to_steam_gateway(self):
    self.assertIsInstance(self.adapter, SteamGateway)


class TestDiscordAdapter(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = DiscordAdapter(self.mock_client)

  def test_discord_adapter_conforms_to_notification_gateway(self):
    self.assertIsInstance(self.adapter, NotificationGateway)

  async def test_send_notification_empty_url_is_noop(self):
    await self.adapter.send_notification("", message="test")
    self.mock_client.post.assert_not_called()

  async def test_send_notification_empty_payload_is_noop(self):
    await self.adapter.send_notification("https://discord.com/api/webhooks/123")
    self.mock_client.post.assert_not_called()

  async def test_send_notification_success(self):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.is_success = True
    mock_resp.status_code = 204
    self.mock_client.post.return_value = mock_resp

    await self.adapter.send_notification(
        "https://discord.com/api/webhooks/123",
        message="Hello world",
        embed={"title": "Test"},
    )
    self.mock_client.post.assert_called_once_with(
        "https://discord.com/api/webhooks/123",
        json={"content": "Hello world", "embeds": [{"title": "Test"}]},
    )
    mock_resp.raise_for_status.assert_called_once()

  async def test_send_notification_3xx_raises_notification_error(self):
    req = httpx.Request("POST", "https://discord.com/api/webhooks/123")
    resp = httpx.Response(302, text="Found Redirect", request=req)
    self.mock_client.post.return_value = resp

    with patch("app.adapters.discord.logger.error") as mock_log:
      with self.assertRaises(NotificationError) as ctx:
        await self.adapter.send_notification(
            "https://discord.com/api/webhooks/123", message="Hi"
        )
      self.assertEqual(ctx.exception.status_code, 302)
      mock_log.assert_called_once()

  async def test_send_notification_4xx_raises_notification_error(self):
    req = httpx.Request("POST", "https://discord.com/api/webhooks/123")
    resp = httpx.Response(400, text="Bad Request: Invalid Webhook Token", request=req)
    self.mock_client.post.return_value = resp

    with patch("app.adapters.discord.logger.error") as mock_log:
      with self.assertRaises(NotificationError) as ctx:
        await self.adapter.send_notification(
            "https://discord.com/api/webhooks/123", message="Hi"
        )
      self.assertEqual(ctx.exception.status_code, 400)
      self.assertIn("Bad Request: Invalid Webhook Token", ctx.exception.details)
      mock_log.assert_called_once()
      log_call = mock_log.call_args[0][0]
      self.assertIn("400", log_call)
      self.assertIn("Bad Request: Invalid Webhook Token", log_call)

  async def test_send_notification_5xx_raises_notification_error(self):
    req = httpx.Request("POST", "https://discord.com/api/webhooks/123")
    resp = httpx.Response(500, text="Internal Server Error on Discord", request=req)
    self.mock_client.post.return_value = resp

    with patch("app.adapters.discord.logger.error") as mock_log:
      with self.assertRaises(NotificationError) as ctx:
        await self.adapter.send_notification(
            "https://discord.com/api/webhooks/123", message="Hi"
        )
      self.assertEqual(ctx.exception.status_code, 500)
      self.assertIn("Internal Server Error on Discord", ctx.exception.details)
      mock_log.assert_called_once()
      log_call = mock_log.call_args[0][0]
      self.assertIn("500", log_call)

  async def test_send_notification_request_error_raises_notification_error(self):
    req = httpx.Request("POST", "https://discord.com/api/webhooks/123")
    self.mock_client.post.side_effect = httpx.ConnectError(
        "Connection refused", request=req
    )

    with patch("app.adapters.discord.logger.error") as mock_log:
      with self.assertRaises(NotificationError) as ctx:
        await self.adapter.send_notification(
            "https://discord.com/api/webhooks/123", message="Hi"
        )
      self.assertEqual(ctx.exception.status_code, 502)
      self.assertIn("Connection refused", str(ctx.exception))
      mock_log.assert_called_once()



if __name__ == "__main__":
  unittest.main()
