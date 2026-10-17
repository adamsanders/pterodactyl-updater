import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.adapters.discord import DiscordAdapter
from app.core.exceptions import NotificationError
from app.core.protocols import NotificationGateway


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
