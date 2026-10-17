from datetime import datetime
import inspect
import logging
from typing import Optional, Union
from app.core.config import TIMING_CONFIG
from app.core.exceptions import NotificationError
from app.core.models import NotificationPreview, ServerModel, SteamPatchNotes
from app.core.protocols import (
    ConfigRepositoryProtocol,
    NotificationGateway,
    PterodactylManagementGateway,
    SteamGateway,
    WebhookPreviewStoreProtocol,
)

logger = logging.getLogger("updater.announcements")


class AnnouncementService:
  """Dedicated service for managing in-game RCON broadcasts and Discord update notifications."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylManagementGateway,
      steam: Optional[SteamGateway] = None,
      discord: Optional[NotificationGateway] = None,
      preview_store: Optional[WebhookPreviewStoreProtocol] = None,
  ):
    self.repo = repository
    self.ptero = ptero
    self.steam = steam
    self.discord = discord
    self.preview_store = preview_store

  def format_countdown_message(self, minutes_left: int) -> str:
    """Formats standard countdown warning text for game chat and notifications."""
    return (
        f"Server will restart in {minutes_left} minute(s) for an update. Please find a safe spot!"
    )

  async def broadcast_warning(
      self,
      server: ServerModel,
      minutes_left: int,
      include_patchnotes: bool = False,
  ) -> None:
    """Broadcasts countdown warnings to in-game chat and Discord webhook subscribers."""
    cfg = self.repo.load()
    msg = self.format_countdown_message(minutes_left)
    is_first = minutes_left == max(TIMING_CONFIG.default_countdown_stages, default=15)

    # 1. In-game console broadcast
    if is_first or server.warn_ingame_countdown:
      logger.info(f"[{server.name}] {msg}")
      if cfg.panel_url and cfg.api_key and server.server_id:
        raw_template = getattr(server, "broadcast_command_template", "say {message}") or "say {message}"
        cmd_template = raw_template.strip() if isinstance(raw_template, str) and raw_template.strip() else "say {message}"
        try:
          if "{message}" in cmd_template:
            cmd = cmd_template.replace("{message}", msg)
          else:
            _ = cmd_template.format()
            cmd = f"{cmd_template} {msg}"
        except Exception:
          cmd = f"say {msg}"
        await self.ptero.send_command(
            cfg.panel_url, cfg.api_key, server.server_id, cmd
        )

    # 2. Discord notification
    if cfg.discord_webhook and (
        server.discord_alerts and (is_first or server.warn_discord_countdown)
    ):
      embed = None
      if include_patchnotes and self.steam:
        notes = await self.steam.fetch_patchnotes(server.app_id)
        if notes:
          embed = notes

      await self.dispatch_notification(
          server_name=server.name,
          message=f"⚠️ **[{server.name}]** {msg}",
          embed=embed,
          test_mode=cfg.test_mode,
          webhook_url=cfg.discord_webhook,
      )

  async def send_test_alert(self, server: ServerModel) -> tuple[bool, str]:
    """Dispatches a test alert to verify Discord webhook configuration or simulator."""
    cfg = self.repo.load()
    embed = None
    if self.steam and server.app_id and str(server.app_id).strip():
      try:
        notes = await self.steam.fetch_patchnotes(server.app_id)
        if notes:
          embed = notes
      except Exception as e:
        logger.warning(
            f"Failed to fetch patch notes for server {server.name} (app {server.app_id}): {e}"
        )

    msg = f"🧪 **[TEST ALERT]** Testing webhook dispatch for **{server.name}**."

    if cfg.test_mode:
      embed_dict = self._format_embed(embed)
      if self.preview_store:
        self.preview_store.set_preview(
            NotificationPreview(
                server_name=server.name,
                message=msg,
                embed=embed_dict,
                timestamp=datetime.now().strftime("%I:%M %p"),
            )
        )
      return True, "Test simulated (Test Mode ON)"
    elif cfg.discord_webhook:
      if self.discord:
        try:
          await self.discord.send_notification(cfg.discord_webhook, msg, embed)
        except NotificationError as e:
          logger.error(f"Failed to dispatch test alert to Discord: {e}")
          return False, f"Error: Discord webhook dispatch failed ({e})"
        except Exception as e:
          logger.error(f"Unexpected error dispatching test alert to Discord: {e}")
          return False, f"Error: Discord webhook dispatch failed ({e})"
      return True, "Test webhook dispatched to Discord"
    else:
      return False, "Error: No Discord Webhook configured"

  def _format_embed(
      self, embed: Optional[Union[dict, SteamPatchNotes]]
  ) -> Optional[dict]:
    if not embed:
      return None
    if self.discord and hasattr(self.discord, "create_patchnotes_embed"):
      res = self.discord.create_patchnotes_embed(embed)
      if inspect.iscoroutine(res):
        res.close()
      else:
        return res
    if isinstance(embed, dict):
      return embed
    if hasattr(embed, "to_embed"):
      return embed.to_embed()
    if isinstance(embed, SteamPatchNotes) or hasattr(embed, "content"):
      img = getattr(embed, "image_url", None)
      return {
          "title": f"📜 {getattr(embed, 'title', '')}",
          "url": getattr(embed, "url", ""),
          "description": getattr(embed, "content", ""),
          "color": 0x1B2838,
          "footer": {"text": "Steam Official Announcement"},
          "image": {"url": img} if img else None,
      }
    if hasattr(embed, "model_dump"):
      return embed.model_dump()
    return {}

  async def dispatch_notification(
      self,
      server_name: str,
      message: str,
      embed: Optional[Union[dict, SteamPatchNotes]] = None,
      test_mode: bool = False,
      webhook_url: str = "",
  ) -> None:
    """Dispatches payload to live Discord webhook or the in-memory test simulator preview."""
    embed_dict = self._format_embed(embed)
    if test_mode:
      if self.preview_store:
        self.preview_store.set_preview(
            NotificationPreview(
                server_name=server_name,
                message=message,
                embed=embed_dict,
                timestamp=datetime.now().strftime("%I:%M %p"),
            )
        )
    elif webhook_url and self.discord:
      try:
        await self.discord.send_notification(
            webhook_url=webhook_url,
            message=message,
            embed=embed,
        )
      except NotificationError as e:
        logger.error(
            f"[{server_name}] Failed to dispatch announcement notification to Discord: {e}"
        )
