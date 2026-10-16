import logging
from typing import Optional
import httpx
from app.core.exceptions import NotificationError

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
      res = await self._client.post(webhook_url, json=payload)
      res.raise_for_status()
      if not res.is_success:
        raise httpx.HTTPStatusError(
            f"Discord webhook non-success status: {res.status_code}",
            request=res.request,
            response=res,
        )
    except httpx.HTTPStatusError as e:
      status_code = e.response.status_code
      body_text = e.response.text
      logger.error(
          f"Discord webhook failed with HTTP {status_code}: {body_text}"
      )
      raise NotificationError(
          f"Discord webhook failed with HTTP {status_code}: {body_text}",
          status_code=status_code,
          details=body_text,
      ) from e
    except httpx.RequestError as e:
      logger.error(f"Discord webhook request error: {e}")
      raise NotificationError(
          f"Discord webhook request error: {e}",
          status_code=502,
          details=str(e),
      ) from e