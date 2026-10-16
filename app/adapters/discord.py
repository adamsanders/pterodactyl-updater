import logging
from typing import Any, Optional, Union
import httpx
from app.core.exceptions import NotificationError
from app.core.models import SteamPatchNotes

logger = logging.getLogger("updater.discord")


class DiscordAdapter:

  def __init__(self, client: httpx.AsyncClient):
    self._client = client

  @staticmethod
  def create_patchnotes_embed(notes: Union[SteamPatchNotes, dict, Any]) -> dict[str, Any]:
    """Builds a Discord embed dictionary from a SteamPatchNotes domain model or existing dictionary."""
    if isinstance(notes, dict):
      return notes
    if isinstance(notes, SteamPatchNotes) or (
        hasattr(notes, "title") and hasattr(notes, "content") and hasattr(notes, "url")
    ):
      embed: dict[str, Any] = {
          "title": f"📜 {notes.title}",
          "url": notes.url,
          "description": notes.content,
          "color": 0x1B2838,
          "footer": {"text": "Steam Official Announcement"},
      }
      image_url = getattr(notes, "image_url", None)
      if image_url:
        embed["image"] = {"url": image_url}
      return embed
    if hasattr(notes, "to_embed"):
      return notes.to_embed()
    return {}

  async def send_notification(
      self,
      webhook_url: str,
      message: Optional[str] = None,
      embed: Optional[Union[dict, SteamPatchNotes]] = None,
  ) -> None:
    if not webhook_url:
      return

    payload = {}
    if message:
      payload["content"] = message
    if embed:
      embed_payload = self.create_patchnotes_embed(embed)
      if embed_payload:
        payload["embeds"] = [embed_payload]

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