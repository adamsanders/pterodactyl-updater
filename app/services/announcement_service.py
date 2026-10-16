from datetime import datetime
import logging
from typing import Optional
from app.core.config import TIMING_CONFIG
from app.core.exceptions import NotificationError
from app.core.models import ServerModel, WebhookPreview
from app.core.protocols import (
    ConfigRepositoryProtocol,
    NotificationGateway,
    PterodactylGateway,
    SteamGateway,
)
from app.services.preview_store import WebhookPreviewStore

logger = logging.getLogger("updater.announcements")


class AnnouncementService:
  """Dedicated service for managing in-game RCON broadcasts and Discord update notifications."""

  def __init__(
      self,
      repository: ConfigRepositoryProtocol,
      ptero: PterodactylGateway,
      steam: Optional[SteamGateway] = None,
      discord: Optional[NotificationGateway] = None,
      preview_store: Optional[WebhookPreviewStore] = None,
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
        await self.ptero.send_command(
            cfg.panel_url, cfg.api_key, server.server_id, f"say {msg}"
        )

    # 2. Discord notification
    if cfg.discord_webhook and (
        server.discord_alerts and (is_first or server.warn_discord_countdown)
    ):
      embed = None
      if include_patchnotes and self.steam:
        embed = await self.steam.fetch_patchnotes(server.app_id)

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
    if self.steam:
      embed = await self.steam.fetch_patchnotes(server.app_id)

    msg = f"🧪 **[TEST ALERT]** Testing webhook dispatch for **{server.name}**."

    if cfg.test_mode:
      if self.preview_store:
        self.preview_store.set_preview(
            WebhookPreview(
                server_name=server.name,
                message=msg,
                embed=embed,
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
      return True, "Test webhook dispatched to Discord"
    else:
      return False, "Error: No Discord Webhook configured"

  async def dispatch_notification(
      self,
      server_name: str,
      message: str,
      embed: Optional[dict] = None,
      test_mode: bool = False,
      webhook_url: str = "",
  ) -> None:
    """Dispatches payload to live Discord webhook or the in-memory test simulator preview."""
    if test_mode:
      if self.preview_store:
        self.preview_store.set_preview(
            WebhookPreview(
                server_name=server_name,
                message=message,
                embed=embed,
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
