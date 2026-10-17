import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.adapters.discord import DiscordAdapter
from app.adapters.simulated_steam import SimulatedSteamAdapter
from app.adapters.steam import SteamAdapter
from app.core.models import SteamPatchNotes, SteamSearchResult
from app.core.protocols import SteamGateway


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

    # Verify embed formatting via DiscordAdapter
    embed = DiscordAdapter.create_patchnotes_embed(notes)
    self.assertEqual(embed["title"], "📜 Version 1.5 Update")
    self.assertEqual(embed["url"], "https://steamcommunity.com/news/123")
    self.assertIn("**Patch notes**", embed["description"])
    self.assertEqual(embed["image"]["url"], "https://clan.cloudflare.steamstatic.com/banner.png")
    self.assertEqual(embed["color"], 0x1B2838)

    # Verify pure DTO attribute access
    self.assertEqual(notes.title, "Version 1.5 Update")
    self.assertEqual(notes.url, "https://steamcommunity.com/news/123")


class TestSteamAdapterSearch(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.mock_client = AsyncMock(spec=httpx.AsyncClient)
    self.adapter = SteamAdapter(self.mock_client)

  async def test_search_empty_query_returns_popular_catalog(self):
    results = await self.adapter.search_games("")
    self.assertGreaterEqual(len(results), 5)
    app_ids = [r.app_id for r in results]
    self.assertIn("2278520", app_ids)  # Enshrouded
    self.assertIn("896660", app_ids)   # Valheim

  async def test_search_games_from_catalog(self):
    results = await self.adapter.search_games("enshrouded")
    self.assertGreaterEqual(len(results), 1)
    enshrouded = next(r for r in results if r.app_id == "2278520")
    self.assertIn("Enshrouded", enshrouded.name)
    self.assertEqual(enshrouded.type, "dedicated_server")

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
    app_ids = [r.app_id for r in results]
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
    self.assertEqual(results, [SteamSearchResult(app_id="2278520", name="Enshrouded")])
    self.real_steam.search_games.assert_called_once_with("enshrouded")

  def test_simulated_steam_adapter_conforms_to_steam_gateway(self):
    self.assertIsInstance(self.adapter, SteamGateway)


if __name__ == "__main__":
  unittest.main()
