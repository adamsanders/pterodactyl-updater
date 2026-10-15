import asyncio
import logging
import re
import time
from typing import Optional, Tuple
from app.adapters.power_tracker import PowerStateTracker
from urllib.parse import urlparse
import httpx

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
  ) -> Tuple[Optional[str], Optional[int]]:
    """Extracts routable internal IP/alias and allocation port with local caching."""
    now = time.time()
    if not hasattr(self, "_allocations_cache"):
      self._allocations_cache = {}

    cached = self._allocations_cache.get(server_id)
    if cached and cached["expires"] > now:
      return cached["ip"], cached["port"]

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
          return resolved_ip, port
    except Exception as e:
      logger.warning(f"Failed to fetch allocation for {server_id}: {e}")
    return None, None

  async def get_server_name(
      self, panel_url: str, api_key: str, server_id: str
  ) -> Tuple[Optional[str], Optional[str]]:
    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}"
    try:
      res = await self._client.get(url, headers=self._headers(api_key))
      if res.status_code == 200:
        return res.json().get("attributes", {}).get("name"), None
      return None, f"Panel HTTP {res.status_code}"
    except Exception as e:
      return None, f"Request error: {e}"

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
      self, panel_url: str, api_key: str, server_id: str, signal: str
  ) -> Tuple[bool, Optional[str]]:
    url = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/power"
    try:
      res = await self._client.post(
          url, json={"signal": signal}, headers=self._headers(api_key)
      )
      if res.status_code in [200, 204]:
        # Seed the tracker with the initiated signal
        self._tracker.register_signal(server_id, signal)
        return True, None
      return False, f"Panel HTTP {res.status_code}: {res.text}"
    except Exception as e:
      return False, f"Request error: {e}"

  async def trigger_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> Tuple[bool, Optional[str]]:
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
    return success, err

  async def get_local_build(
      self, panel_url: str, api_key: str, server_id: str, manifest_path: str
  ) -> Tuple[Optional[str], Optional[str]]:
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
          return match.group(1), None
        return None, "File found, but could not parse 'buildid'"
      return None, f"Panel HTTP {res.status_code}"
    except Exception as e:
      return None, f"Request error: {e}"

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
      self, panel_url: str, api_key: str, server_id: str, new_name: str
  ) -> Tuple[bool, Optional[str]]:
    url = (
        f"{panel_url.rstrip('/')}/api/client/servers/{server_id}/settings/rename"
    )
    try:
      res = await self._client.post(
          url, json={"name": new_name}, headers=self._headers(api_key)
      )
      if res.status_code in [200, 204]:
        return True, None
      return False, f"Panel HTTP {res.status_code}: {res.text}"
    except Exception as e:
      return False, f"Request error: {e}"

  async def execute_graceful_restart(
      self, panel_url: str, api_key: str, server_id: str
  ) -> None:
    await self.trigger_restart(panel_url, api_key, server_id)