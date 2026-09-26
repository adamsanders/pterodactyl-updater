import logging
from typing import Optional
import httpx

logger = logging.getLogger("updater.discord")


class DiscordAdapter:

  def __init__(self, client: httpx.AsyncClient):
    self._client = client

  async def send_notification(
      self,
      webhook_url: str,
      message: Optional[str] = None,
      embed: Optional[dict] = None,
  ) -> None:
    if not webhook_url:
      return

    payload = {}
    if message:
      payload["content"] = message
    if embed:
      payload["embeds"] = [embed]

    if not payload:
      return

    try:
      await self._client.post(webhook_url, json=payload)
    except Exception as e:
      logger.error(f"Failed to dispatch Discord webhook: {e}")