import unittest
from unittest.mock import AsyncMock, MagicMock
import httpx

from app.adapters.discord import DiscordAdapter
from app.core.models import SteamPatchNotes


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
