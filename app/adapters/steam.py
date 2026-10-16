import logging
from typing import Optional
from app.adapters.steam_content_parser import parse_steam_content
from app.core.catalogs import (
    GAME_TO_SERVER_APPID,
    POPULAR_DEDICATED_SERVERS,
    resolve_game_appid,
)
from app.core.exceptions import SteamApiError
from app.core.models import SteamPatchNotes, SteamSearchResult
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

  @staticmethod
  def _clean_content(text: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Legacy forwarding wrapper delegating content parsing to parse_steam_content."""
    return parse_steam_content(text)

  async def fetch_patchnotes(
      self, appid: int | str, raise_on_error: bool = False
  ) -> Optional[SteamPatchNotes]:
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

          date_val = str(post.get("date", "")) if post.get("date") else None
          return SteamPatchNotes(
              title=post.get("title", "New Update Released"),
              content=clean_content,
              url=link,
              image_url=image_url,
              posted_at=date_val,
          )
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

  async def search_games(self, query: str) -> list[SteamSearchResult]:
    """Searches for games and dedicated servers matching a query."""
    q = query.strip()
    if not q:
      return [
          SteamSearchResult(
              appid=srv["app_id"],
              app_id=srv["app_id"],
              name=srv["name"],
              type="dedicated_server",
          )
          for srv in POPULAR_DEDICATED_SERVERS[:15]
      ]

    results: list[SteamSearchResult] = []
    seen_appids: set[str] = set()

    # 1. Match known dedicated server catalog
    q_lower = q.lower()
    for srv in POPULAR_DEDICATED_SERVERS:
      if (
          q_lower in srv["name"].lower()
          or q_lower in srv.get("game", "").lower()
          or q == srv["app_id"]
      ):
        if srv["app_id"] not in seen_appids:
          seen_appids.add(srv["app_id"])
          results.append(
              SteamSearchResult(
                  appid=srv["app_id"],
                  app_id=srv["app_id"],
                  name=srv["name"],
                  type="dedicated_server",
              )
          )

    # 2. Query Steam Store Search API
    try:
      url = f"https://store.steampowered.com/api/storesearch/?term={q}&l=english&cc=US"
      res = await self._client.get(url, headers=self.headers, timeout=3.0)
      if res.status_code == 200:
        items = res.json().get("items", [])
        for item in items:
          item_id = str(item.get("id"))
          item_name = item.get("name", "")

          # Check if this game maps to a known dedicated server
          dedi_id = GAME_TO_SERVER_APPID.get(item_id)
          if dedi_id and dedi_id not in seen_appids:
            seen_appids.add(dedi_id)
            results.append(
                SteamSearchResult(
                    appid=dedi_id,
                    app_id=dedi_id,
                    name=f"{item_name} Dedicated Server",
                    type="dedicated_server",
                )
            )

          if item_id not in seen_appids:
            seen_appids.add(item_id)
            results.append(
                SteamSearchResult(
                    appid=item_id,
                    app_id=item_id,
                    name=item_name,
                    type="game",
                )
            )
    except Exception as e:
      logger.debug(f"Steam store search failed for '{q}': {e}")

    return results[:15]