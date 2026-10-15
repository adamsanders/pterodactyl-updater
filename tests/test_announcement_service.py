import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.models import AppConfigModel, ServerModel
from app.services.announcement_service import AnnouncementService
from app.services.preview_store import WebhookPreviewStore


class TestAnnouncementService(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.repo = MagicMock()
    self.ptero = AsyncMock()
    self.steam = AsyncMock()
    self.discord = AsyncMock()
    self.preview_store = WebhookPreviewStore()

    self.service = AnnouncementService(
        repository=self.repo,
        ptero=self.ptero,
        steam=self.steam,
        discord=self.discord,
        preview_store=self.preview_store,
    )

  def test_format_countdown_message(self):
    msg = self.service.format_countdown_message(10)
    self.assertEqual(
        msg,
        "Server will restart in 10 minute(s) for an update. Please find a safe spot!",
    )

  async def test_broadcast_warning_initial_stage(self):
    srv = ServerModel(
        name="Valheim Dedicated",
        server_id="srv_valheim",
        app_id="896660",
        warn_ingame_countdown=True,
        discord_alerts=True,
    )
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="ptlc_key",
        discord_webhook="https://discord.com/webhook",
        test_mode=False,
    )
    self.repo.load.return_value = cfg
    self.steam.fetch_patchnotes.return_value = {"title": "Update 0.218"}

    await self.service.broadcast_warning(
        server=srv, minutes_left=15, include_patchnotes=True
    )

    # 1. In-game broadcast sent via Pterodactyl
    self.ptero.send_command.assert_called_once_with(
        "http://panel.test",
        "ptlc_key",
        "srv_valheim",
        "say Server will restart in 15 minute(s) for an update. Please find a safe spot!",
    )

    # 2. Steam patch notes fetched
    self.steam.fetch_patchnotes.assert_called_once_with("896660")

    # 3. Discord notification dispatched
    self.discord.send_notification.assert_called_once()
    args, kwargs = self.discord.send_notification.call_args
    self.assertEqual(kwargs.get("webhook_url"), "https://discord.com/webhook")
    self.assertIn("15 minute(s)", kwargs.get("message"))
    self.assertEqual(kwargs.get("embed"), {"title": "Update 0.218"})

  async def test_broadcast_warning_test_mode_sets_preview(self):
    srv = ServerModel(
        name="Palworld",
        server_id="srv_palworld",
        app_id="2394010",
        warn_ingame_countdown=True,
        discord_alerts=True,
    )
    cfg = AppConfigModel(
        panel_url="http://panel.test",
        api_key="ptlc_key",
        discord_webhook="https://discord.com/webhook",
        test_mode=True,
    )
    self.repo.load.return_value = cfg

    await self.service.broadcast_warning(
        server=srv, minutes_left=10, include_patchnotes=False
    )

    # Discord network adapter should NOT be called in test mode
    self.discord.send_notification.assert_not_called()

    # Preview store should receive simulated webhook
    preview = self.preview_store.get_preview()
    self.assertIsNotNone(preview)
    self.assertEqual(preview.server_name, "Palworld")
    self.assertIn("10 minute(s)", preview.message)

  async def test_send_test_alert_modes(self):
    srv = ServerModel(name="Rust", server_id="srv_rust", app_id="258550")
    self.steam.fetch_patchnotes.return_value = None

    # 1. Test Mode ON
    cfg_test = AppConfigModel(discord_webhook="https://discord.com/webhook", test_mode=True)
    self.repo.load.return_value = cfg_test
    success, msg = await self.service.send_test_alert(srv)
    self.assertTrue(success)
    self.assertEqual(msg, "Test simulated (Test Mode ON)")

    # 2. Live Discord Mode
    cfg_live = AppConfigModel(discord_webhook="https://discord.com/webhook", test_mode=False)
    self.repo.load.return_value = cfg_live
    success, msg = await self.service.send_test_alert(srv)
    self.assertTrue(success)
    self.assertEqual(msg, "Test webhook dispatched to Discord")
    self.discord.send_notification.assert_called_once()

    # 3. Unconfigured Webhook
    cfg_none = AppConfigModel(discord_webhook="", test_mode=False)
    self.repo.load.return_value = cfg_none
    success, msg = await self.service.send_test_alert(srv)
    self.assertFalse(success)
    self.assertEqual(msg, "Error: No Discord Webhook configured")


if __name__ == "__main__":
  unittest.main()
