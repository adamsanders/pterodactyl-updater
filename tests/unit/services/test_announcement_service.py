import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import NotificationError
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
        warn_discord_countdown=True,
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

    # 4. Live Discord failure returns error tuple rather than raising
    cfg_fail = AppConfigModel(discord_webhook="https://discord.com/webhook", test_mode=False)
    self.repo.load.return_value = cfg_fail
    self.discord.send_notification.side_effect = NotificationError(
        "Discord webhook failed with HTTP 400", status_code=400
    )
    with patch("app.services.announcement_service.logger.error") as mock_log:
      success, msg = await self.service.send_test_alert(srv)
      self.assertFalse(success)
      self.assertIn("Error: Discord webhook dispatch failed", msg)
      mock_log.assert_called_once()

  async def test_broadcast_warning_notification_error_is_logged_and_does_not_crash(self):
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
    self.steam.fetch_patchnotes.return_value = None
    self.discord.send_notification.side_effect = NotificationError(
        "Discord 500 Internal Server Error", status_code=500
    )

    with patch("app.services.announcement_service.logger.error") as mock_log:
      # Must not raise NotificationError so scheduled update countdown survives
      await self.service.broadcast_warning(
          server=srv, minutes_left=15, include_patchnotes=False
      )
      mock_log.assert_called_once()
      self.assertIn("Failed to dispatch announcement notification", mock_log.call_args[0][0])

  async def test_broadcast_warning_safe_templating_with_extra_braces_and_symbols(self):
    test_cases = [
        (
            "say {{ALERT}} {message} {{END}}",
            "say {{ALERT}} Server will restart in 5 minute(s) for an update. Please find a safe spot! {{END}}",
        ),
        (
            "broadcast {invalid_format:10s} {message}",
            "broadcast {invalid_format:10s} Server will restart in 5 minute(s) for an update. Please find a safe spot!",
        ),
        (
            'servermsg [ADMIN:100%] "{message}" {unclosed',
            'servermsg [ADMIN:100%] "Server will restart in 5 minute(s) for an update. Please find a safe spot!" {unclosed',
        ),
        (
            "say {0} {name} {message} %s $PATH",
            "say {0} {name} Server will restart in 5 minute(s) for an update. Please find a safe spot! %s $PATH",
        ),
        (
            "say {message} (REPEAT: {message})",
            "say Server will restart in 5 minute(s) for an update. Please find a safe spot! (REPEAT: Server will restart in 5 minute(s) for an update. Please find a safe spot!)",
        ),
        (
            "   ",
            "say Server will restart in 5 minute(s) for an update. Please find a safe spot!",
        ),
        (
            "broadcast {unclosed",
            "say Server will restart in 5 minute(s) for an update. Please find a safe spot!",
        ),
    ]

    for template, expected_cmd in test_cases:
      with self.subTest(template=template):
        self.ptero.reset_mock()
        srv = ServerModel(
            name="Templated Game Server",
            server_id="srv_templ",
            warn_ingame_countdown=True,
            broadcast_command_template=template,
        )
        cfg = AppConfigModel(
            panel_url="http://panel.test",
            api_key="ptlc_key",
            servers=[srv],
        )
        self.repo.load.return_value = cfg

        await self.service.broadcast_warning(server=srv, minutes_left=5)

        self.ptero.send_command.assert_called_once_with(
            "http://panel.test",
            "ptlc_key",
            "srv_templ",
            expected_cmd,
        )

  async def test_send_test_alert_test_mode_sets_preview(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=True, servers=[srv])
    self.repo.load.return_value = cfg
    self.steam.fetch_patchnotes.return_value = {"title": "Test Patch", "description": "Notes"}

    success, msg = await self.service.send_test_alert(srv)
    self.assertTrue(success)
    self.assertEqual(msg, "Test simulated (Test Mode ON)")

    preview = self.preview_store.get_preview()
    self.assertIsNotNone(preview)
    self.assertEqual(preview.server_name, "Valheim Dedicated")
    self.assertIn("TEST ALERT", preview.message)
    self.assertEqual(preview.embed, {"title": "Test Patch", "description": "Notes"})
    self.discord.send_notification.assert_not_called()

  async def test_send_test_alert_discord_webhook_success(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=False, discord_webhook="https://discord.com/webhook", servers=[srv])
    self.repo.load.return_value = cfg
    self.steam.fetch_patchnotes.return_value = None

    success, msg = await self.service.send_test_alert(srv)
    self.assertTrue(success)
    self.assertEqual(msg, "Test webhook dispatched to Discord")
    self.discord.send_notification.assert_called_once()
    self.assertIsNone(self.preview_store.get_preview())

  async def test_send_test_alert_discord_webhook_notification_error_handled(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=False, discord_webhook="https://discord.com/webhook", servers=[srv])
    self.repo.load.return_value = cfg
    self.discord.send_notification.side_effect = NotificationError("Rate limited", status_code=429)

    success, msg = await self.service.send_test_alert(srv)
    self.assertFalse(success)
    self.assertIn("Error: Discord webhook dispatch failed", msg)

  async def test_send_test_alert_discord_unexpected_exception_handled(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=False, discord_webhook="https://discord.com/webhook", servers=[srv])
    self.repo.load.return_value = cfg
    self.discord.send_notification.side_effect = RuntimeError("Socket dropped")

    success, msg = await self.service.send_test_alert(srv)
    self.assertFalse(success)
    self.assertIn("Error: Discord webhook dispatch failed", msg)

  async def test_send_test_alert_no_webhook_configured(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=False, discord_webhook="", servers=[srv])
    self.repo.load.return_value = cfg

    success, msg = await self.service.send_test_alert(srv)
    self.assertFalse(success)
    self.assertEqual(msg, "Error: No Discord Webhook configured")
    self.discord.send_notification.assert_not_called()

  async def test_send_test_alert_steam_patchnotes_error_resilience(self):
    srv = ServerModel(name="Valheim Dedicated", server_id="srv-1", app_id="896660")
    cfg = AppConfigModel(test_mode=True, servers=[srv])
    self.repo.load.return_value = cfg
    self.steam.fetch_patchnotes.side_effect = Exception("Steam API unreachable")

    # Should not raise exception and should still succeed in test mode
    success, msg = await self.service.send_test_alert(srv)
    self.assertTrue(success)
    self.assertEqual(msg, "Test simulated (Test Mode ON)")
    preview = self.preview_store.get_preview()
    self.assertIsNotNone(preview)
    self.assertIsNone(preview.embed)


if __name__ == "__main__":
  unittest.main()
