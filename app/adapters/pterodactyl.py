import asyncio
import logging
import re
import time
from typing import Optional, Tuple
from urllib.parse import urlparse
import httpx

from app.adapters.power_tracker import PowerStateTracker
from app.core.config import IGNORED_STEAM_APPIDS, POPULAR_DEDICATED_SERVERS
from app.core.exceptions import PterodactylApiError
from app.core.models import (
    LocalBuildResult,
    OperationResult,
    ServerAllocation,
    ServerNameResult,
)

logger = logging.getLogger("updater.pterodactyl")


class PterodactylAdapter:

  def __init__(self, client: httpx.AsyncClient):
    self._client = client
    self._tracker = PowerStateTracker()

  def _headers(self, api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.pterodactyl.v1+json",
        "Content-Type": "application/json",
    }

  def consume_startup_transition(self, server_id: str) -> bool:
      return self._tracker.pop_just_started(server_id)

  def invalidate_power_cache(self, server_id: Optional[str] = None) -> None:
    """Delegates cache flushing to the underlying PowerStateTracker."""
    self._tracker.invalidate(server_id)

  async def get_external_ip(self) -> Optional[str]:
        now = time.time()
        if hasattr(self, "_external_ip_cache"):
            cached_ip, expires = self._external_ip_cache
            if expires > now:
                return cached_ip

        try:
            res = await self._client.get("https://api.ipify.org?format=json", timeout=3.0)
            if res.status_code == 200:
                ip = res.json().get("ip")
                self._external_ip_cache = (ip, now + 3600.0)  # 1-hour TTL
                return ip
        except Exception:
            pass
        return getattr(self, "_external_ip_cache", (None, 0))[0]

  async def get_server_allocation(
      self, panel_url: str, api_key: str, server_id: str
  ) -> ServerAllocation:
    """Extracts routable internal IP/alias and allocation port with local caching."""
    now = time.time()
    if not hasattr(self, "_allocations_cache"):
      self._allocations_cache = {}

    cached = self._allocations_cache.get(server_id)
    if cached and cached["expires"] > now:
      return ServerAllocation(cached["ip"], cached["port"])

    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}?include=allocations"
    try:
      res = await self._client.get(url, headers=self._headers(api_key))
      if res.status_code == 200:
        data = res.json().get("attributes", {})
        allocations = (
            data.get("relationships", {})
            .get("allocations", {})
            .get("data", [])
        )
        primary = next(
            (
                a["attributes"]
                for a in allocations
                if a.get("attributes", {}).get("is_default")
            ),
            None,
        )
        if not primary and allocations:
          primary = allocations[0].get("attributes", {})

        if primary:
          port = primary.get("port")
          raw_ip = primary.get("ip")
          alias = primary.get("alias") or primary.get("ip_alias")

          # 1. Prefer alias if defined (e.g. 192.168.0.234)
          resolved_ip = alias or raw_ip

          # 2. If bound to wildcard 0.0.0.0, fallback to the host in panel_url
          if (
              not resolved_ip
              or resolved_ip == "0.0.0.0"
              or resolved_ip.startswith("127.")
          ):
            if panel_url:
              parsed = urlparse(
                  panel_url if "://" in panel_url else f"http://{panel_url}"
              )
              if parsed.hostname and parsed.hostname not in (
                  "0.0.0.0",
                  "localhost",
              ):
                resolved_ip = parsed.hostname

          self._allocations_cache[server_id] = {
              "ip": resolved_ip,
              "port": port,
              "expires": now + 60.0,
          }
          return ServerAllocation(resolved_ip, port)
    except Exception as e:
      logger.warning(f"Failed to fetch allocation for {server_id}: {e}")
    return ServerAllocation(None, None)

  async def get_server_name(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
      raise_on_error: bool = False,
  ) -> ServerNameResult:
    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}"
    try:
      res = await self._client.get(url, headers=self._headers(api_key))
      if res.status_code == 200:
        return ServerNameResult(res.json().get("attributes", {}).get("name"), None)
      result = ServerNameResult(None, f"Panel HTTP {res.status_code}")
    except Exception as e:
      result = ServerNameResult(None, f"Request error: {e}")

    if raise_on_error:
      result.raise_if_failed(server_id=server_id)
    return result

  async def detect_server_details(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
  ) -> dict:
    """Attempts to auto-detect server name, Steam App ID, and manifest path from Pterodactyl."""
    details = {
        "name": None,
        "app_id": None,
        "manifest_path": None,
    }
    headers = self._headers(api_key)
    base_url = panel_url.rstrip("/")

    # 1. Fetch general server details (name)
    try:
      res = await self._client.get(f"{base_url}/api/client/servers/{server_id}", headers=headers)
      if res.status_code == 200:
        attrs = res.json().get("attributes", {})
        details["name"] = attrs.get("name")
        invocation = attrs.get("invocation", "")
        m = re.search(r"app_update\s+(\d+)", invocation)
        if m and m.group(1) not in IGNORED_STEAM_APPIDS:
          details["app_id"] = m.group(1)
    except Exception as e:
      logger.warning(f"Error fetching server details for {server_id}: {e}")

    # 2. Check startup parameters/variables and startup commands for App ID
    try:
      res = await self._client.get(f"{base_url}/api/client/servers/{server_id}/startup", headers=headers)
      if res.status_code == 200:
        json_data = res.json()
        meta = json_data.get("meta", {})
        cmd = f"{meta.get('startup_command', '')} {meta.get('raw_startup_command', '')}"
        m = re.search(r"app_update\s+(\d+)", cmd)
        if m and m.group(1) not in IGNORED_STEAM_APPIDS:
          details["app_id"] = m.group(1)

        if not details["app_id"]:
          data = json_data.get("data", [])
          for item in data:
            vattrs = item.get("attributes", {})
            env_var = (vattrs.get("env_variable") or "").upper()
            var_name = (vattrs.get("name") or "").lower()
            val = str(vattrs.get("server_value") or vattrs.get("default_value") or "").strip()
            if (
                env_var in ("STEAM_APP_ID", "STEAM_APPID", "APP_ID", "APPID", "SRCDS_APPID", "GAME_ID", "GAME_APP_ID", "VANILLA_APPID")
                or "app id" in var_name
                or "appid" in var_name
            ) and val.isdigit() and val not in IGNORED_STEAM_APPIDS:
              details["app_id"] = val
              break
    except Exception as e:
      logger.debug(f"Could not inspect startup variables for {server_id}: {e}")

    # 3. Check file list for appmanifest_<appid>.acf (filtering out 1007 / 228980 redistributables)
    try:
      res = await self._client.get(f"{base_url}/api/client/servers/{server_id}/files/list?directory=steamapps", headers=headers)
      if res.status_code == 200:
        files = res.json().get("data", [])
        valid_manifests: list[tuple[str, str]] = []
        for f in files:
          fname = f.get("attributes", {}).get("name", "")
          m = re.match(r"^appmanifest_(\d+)\.acf$", fname)
          if m:
            aid = m.group(1)
            if aid not in IGNORED_STEAM_APPIDS:
              valid_manifests.append((aid, f"steamapps/{fname}"))

        # If app_id was already detected from startup, look for its exact manifest
        if details["app_id"]:
          for aid, mpath in valid_manifests:
            if aid == details["app_id"]:
              details["manifest_path"] = mpath
              break

        # If app_id not yet known, choose the game manifest (preferring catalog matches)
        if not details["app_id"] and valid_manifests:
          catalog_appids = {s["app_id"] for s in POPULAR_DEDICATED_SERVERS}
          chosen = next((item for item in valid_manifests if item[0] in catalog_appids), valid_manifests[0])
          details["app_id"] = chosen[0]
          details["manifest_path"] = chosen[1]
    except Exception as e:
      logger.debug(f"Could not inspect steamapps directory for {server_id}: {e}")

    # 4. If still not detected, try matching server name against known popular servers catalog
    if not details["app_id"] and details.get("name"):
      name_lower = details["name"].lower()
      for srv in POPULAR_DEDICATED_SERVERS:
        srv_name_lower = srv["name"].lower()
        game_lower = srv.get("game", "").lower()
        if (game_lower and game_lower in name_lower) or (srv_name_lower in name_lower):
          details["app_id"] = srv["app_id"]
          break

    # If app_id was found but no specific manifest file was located, use standard path convention
    if details["app_id"] and not details["manifest_path"]:
      details["manifest_path"] = f"steamapps/appmanifest_{details['app_id']}.acf"

    return details

  async def get_power_state(
      self, panel_url: str, api_key: str, server_id: str
  ) -> str:
    # 1. Return fresh cached state if valid
    cached = self._tracker.get_valid_cache(server_id)
    if cached is not None:
      return cached

    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/resources"
    try:
      res = await self._client.get(url, headers=self._headers(api_key))
      if res.status_code == 200:
        raw_state = (
            res.json().get("attributes", {}).get("current_state", "offline")
        )
        return self._tracker.filter_state(server_id, raw_state)
    except Exception as e:
      logger.warning(
          f"Power state query failed for {server_id}: {e}. Retaining smoothed"
          " state."
      )

    return self._tracker.filter_state(server_id, "unknown")

  async def send_power_signal(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
      signal: str,
      raise_on_error: bool = False,
  ) -> OperationResult:
    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/power"
    try:
      res = await self._client.post(
          url, json={"signal": signal}, headers=self._headers(api_key)
      )
      if res.status_code in [200, 204]:
        # Seed the tracker with the initiated signal
        self._tracker.register_signal(server_id, signal)
        return OperationResult(True, None)
      result = OperationResult(False, f"Panel HTTP {res.status_code}: {res.text}")
    except Exception as e:
      result = OperationResult(False, f"Request error: {e}")

    if raise_on_error:
      result.raise_if_failed(server_id=server_id)
    return result

  async def trigger_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> OperationResult:
    power_state = await self.get_power_state(panel_url, api_key, server_id)
    signal = "start" if power_state == "offline" else "restart"
    success, err = await self.send_power_signal(
        panel_url, api_key, server_id, signal
    )
    if not success and signal == "restart":
      success, err = await self.send_power_signal(
          panel_url, api_key, server_id, "start"
      )
    if success:
      logger.info(
          f"Power signal '{signal}' successfully dispatched to server {server_id} via Pterodactyl API."
      )
    else:
      logger.error(
          f"Failed to restart server {server_id} via Pterodactyl API: {err}"
      )
    return OperationResult(success, err)

  async def get_local_build(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
      manifest_path: str,
      raise_on_error: bool = False,
  ) -> LocalBuildResult:
    if not manifest_path or not server_id:
      result = LocalBuildResult(None, "Manifest path or server ID is not configured")
      if raise_on_error:
        result.raise_if_failed(server_id=server_id)
      return result

    clean_manifest = manifest_path.lstrip("/")
    url = (
        f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/files/contents"
    )
    headers = self._headers(api_key)
    headers.update({
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    })
    params = {"file": clean_manifest, "_t": int(time.time() * 1000)}

    try:
      res = await self._client.get(url, params=params, headers=headers)
      if res.status_code == 200:
        match = re.search(r'"buildid"\s+"(\d+)"', res.text)
        if match:
          return LocalBuildResult(match.group(1), None)
        result = LocalBuildResult(None, "File found, but could not parse 'buildid'")
      else:
        result = LocalBuildResult(None, f"Panel HTTP {res.status_code}")
    except Exception as e:
      result = LocalBuildResult(None, f"Request error: {e}")

    if raise_on_error:
      result.raise_if_failed(server_id=server_id)
    return result

  async def send_command(
      self, panel_url: str, api_key: str, server_id: str, command: str
  ) -> None:
    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/command"
    try:
      await self._client.post(
          url, json={"command": command}, headers=self._headers(api_key)
      )
    except Exception as e:
      logger.error(f"Failed to send command to server {server_id}: {e}")

  async def rename_server(
      self,
      panel_url: str,
      api_key: str,
      server_id: str,
      new_name: str,
      raise_on_error: bool = False,
  ) -> OperationResult:
    url = (
        f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/settings/rename"
    )
    try:
      res = await self._client.post(
          url, json={"name": new_name}, headers=self._headers(api_key)
      )
      if res.status_code in [200, 204]:
        return OperationResult(True, None)
      result = OperationResult(False, f"Panel HTTP {res.status_code}: {res.text}")
    except Exception as e:
      result = OperationResult(False, f"Request error: {e}")

    if raise_on_error:
      result.raise_if_failed(server_id=server_id)
    return result

  async def execute_graceful_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    await self.trigger_restart(panel_url, api_key, server_id)