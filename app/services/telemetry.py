from collections import deque
import time
from typing import Dict, List


class CallTracker:
  """Thread-safe telemetry tracker calculating rolling call frequencies (calls/min)

  and buffering recent API activity logs.
  """

  def __init__(self, max_logs: int = 150):
    self._logs: deque = deque(maxlen=max_logs)
    self._call_history: Dict[str, deque] = {}

  @staticmethod
  def normalize_endpoint(url_str: str) -> str:
    """Normalizes raw API URLs into clean, readable endpoint categories."""
    if "api.ipify.org" in url_str:
      return "ipify: Public IP"
    elif "api.steamcmd.net" in url_str:
      return "SteamCMD: Build Query"
    elif "api.steampowered.com" in url_str:
      return "Steam Web API: News"
    elif "discord.com" in url_str:
      return "Discord: Webhook"
    elif "/resources" in url_str:
      return "Pterodactyl: Resources (Power/Stats)"
    elif "/contents" in url_str:
      return "Pterodactyl: Manifest (Build ID)"
    elif "/power" in url_str:
      return "Pterodactyl: Power Signal"
    elif "/command" in url_str:
      return "Pterodactyl: Console Command"
    elif "/settings/rename" in url_str:
      return "Pterodactyl: Rename Server"
    elif "include=allocations" in url_str or "/allocations" in url_str:
      return "Pterodactyl: Network Allocations"
    elif "/api/client/servers/" in url_str:
      return "Pterodactyl: Server Info"
    elif "/api/status" in url_str:
      return "Internal: /api/status Poll"
    return url_str.split("?")[0]

  def record(
      self,
      endpoint: str,
      method: str = "GET",
      status: str = "200",
      duration_ms: float = 0.0,
      details: str = "",
  ) -> None:
    now = time.time()
    time_str = (
        time.strftime("%H:%M:%S", time.localtime(now))
        + f".{int((now % 1) * 1000):03d}"
    )

    entry = {
        "timestamp": time_str,
        "endpoint": endpoint,
        "method": method.upper(),
        "status": str(status),
        "duration_ms": round(duration_ms, 1),
        "details": details,
    }
    self._logs.append(entry)

    if endpoint not in self._call_history:
      self._call_history[endpoint] = deque()
    self._call_history[endpoint].append(now)

  def _cleanup_old_timestamps(self, now: float) -> None:
    cutoff = now - 60.0  # Rolling 60-second window
    for endpoint, timestamps in list(self._call_history.items()):
      while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()

  def get_rates_per_minute(self) -> List[dict]:
    now = time.time()
    self._cleanup_old_timestamps(now)

    rates = []
    for endpoint, timestamps in self._call_history.items():
      cpm = len(timestamps)
      if cpm > 0:
        rates.append({"endpoint": endpoint, "cpm": cpm})

    # Sort descending by call frequency
    rates.sort(key=lambda x: x["cpm"], reverse=True)
    return rates

  def get_telemetry_snapshot(self) -> dict:
    return {"rates": self.get_rates_per_minute(), "logs": list(self._logs)}

  def clear(self) -> None:
    self._logs.clear()