import html
import json
import logging
import re
from typing import Optional, Tuple
from app.core.config import resolve_game_appid
from app.core.exceptions import SteamApiError
import httpx

logger = logging.getLogger("updater.steam")


class SteamAdapter:

  def __init__(self, client: httpx.AsyncClient):
    self._client = client
    self.headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

  async def get_latest_build(
      self,
      app_id: str,
      server_id: Optional[str] = None,
      raise_on_error: bool = False,
  ) -> Optional[str]:
    url = f"https://api.steamcmd.net/v1/info/{app_id}"
    try:
      res = await self._client.get(
          url, headers={"Cache-Control": "no-cache"}
      )
      if res.status_code == 200:
        data = res.json()
        build_id = (
            data.get("data", {})
            .get(app_id, {})
            .get("depots", {})
            .get("branches", {})
            .get("public", {})
            .get("buildid")
        )
        if build_id:
          return str(build_id)
        if raise_on_error:
          raise SteamApiError(
              f"No public buildid found for AppID {app_id}", app_id=app_id
          )
      elif raise_on_error:
        raise SteamApiError(
            f"SteamCMD API returned HTTP {res.status_code}",
            app_id=app_id,
            status_code=res.status_code,
        )
    except SteamApiError:
      raise
    except Exception as e:
      logger.error(f"Failed connecting to SteamCMD API for App {app_id}: {e}")
      if raise_on_error:
        raise SteamApiError(f"SteamCMD connection error: {e}", app_id=app_id)
    return None

  def _clean_content(self, text: str) -> Tuple[str, Optional[str]]:
    image_url = None
    bb_img = re.search(r"\[img\](.*?)\[/img\]", text, re.IGNORECASE)
    if bb_img:
      image_url = bb_img.group(1).strip()
    else:
      html_img = re.search(
          r"""<img\s+[^>]*?src=["'](.*?)["']""", text, re.IGNORECASE
      )
      if html_img:
        image_url = html_img.group(1).strip()

    if image_url and "{STEAM_CLAN_IMAGE}" in image_url:
      image_url = image_url.replace(
          "{STEAM_CLAN_IMAGE}", "https://clan.cloudflare.steamstatic.com/images"
      )

    text = re.sub(
        r"""<a\s+[^>]*?href=["'](.*?)["'][^>]*?>(.*?)</a>""",
        r"[\2](\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<h[1-6][^>]*>(.*?)</h[1-6]>",
        r"\n### \1\n",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>",
        r"**\1**",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>",
        r"*\1*",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<(?:strike|s|del)[^>]*>(.*?)</(?:strike|s|del)>",
        r"~~\1~~",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<li[^>]*>(.*?)</li>", r"• \1\n", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"<br\s*/?>", r"\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", r"\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", r"\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(
        r"\[b\](.*?)\[/b\]", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r"\[i\](.*?)\[/i\]", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r"\[u\](.*?)\[/u\]", r"__\1__", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(
        r"\[strike\](.*?)\[/strike\]",
        r"~~\1~~",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"\[h[1-6]\](.*?)\[/h[1-6]\]",
        r"\n### \1\n",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"\[url=(.*?)\](.*?)\[/url\]",
        r"[\2](\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"\[/?list\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\*\]", "• ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\[img\].*?\[/img\]", "", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"\[/?[a-zA-Z0-9_\-=:\.\s\"']+\](?!\()", "", text)

    text = html.unescape(text)
    cleaned = "\n".join([line.strip() for line in text.split("\n")])
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip(), image_url

  async def fetch_patchnotes(
      self, appid: int | str, raise_on_error: bool = False
  ) -> Optional[dict]:
    if not appid:
      return None

    game_appid = resolve_game_appid(appid)
    try:
      url = (
          "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
          f"?appid={game_appid}&count=5&maxlength=0&feeds=steam_community_announcements"
      )
      resp = await self._client.get(url, headers=self.headers)
      if resp.status_code == 200:
        items = resp.json().get("appnews", {}).get("newsitems", [])
        if items:
          post = items[0]
          clean_content, image_url = self._clean_content(
              post.get("contents", "")
          )
          link = post.get("url", "")

          if len(clean_content) > 1500:
            clean_content = clean_content[:1500].rsplit(" ", 1)[0] + "..."
            if link:
              clean_content += (
                  f"\n\n🔗 **[Read Full Patch Notes on Steam]({link})**"
              )
          elif link and link not in clean_content:
            clean_content += f"\n\n🔗 **[View Post on Steam]({link})**"

          embed = {
              "title": f"📜 {post.get('title', 'New Update Released')}",
              "url": link,
              "description": clean_content,
              "color": 0x1B2838,
              "footer": {"text": "Steam Official Announcement"},
          }
          if image_url:
            embed["image"] = {"url": image_url}
          return embed
      elif raise_on_error:
        raise SteamApiError(
            f"Steam news API returned HTTP {resp.status_code}",
            app_id=str(appid),
            status_code=resp.status_code,
        )
    except SteamApiError:
      raise
    except Exception as e:
      logger.warning(
          f"Could not fetch Steam news for AppID {game_appid}: {e}"
      )
      if raise_on_error:
        raise SteamApiError(f"Steam news fetch failed: {e}", app_id=str(appid))
    return None