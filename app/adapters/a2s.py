import asyncio
import logging
import time
from typing import Optional, Tuple
from app.core.config import TIMING_CONFIG
from app.core.protocols import CallTrackerProtocol

logger = logging.getLogger("updater.a2s")

A2S_INFO_REQUEST = b"\xff\xff\xff\xff\x54Source Engine Query\x00"


class A2SProtocol(asyncio.DatagramProtocol):

  def __init__(self):
    self.transport: Optional[asyncio.DatagramTransport] = None
    self.queue: asyncio.Queue[bytes] = asyncio.Queue()

  def connection_made(self, transport: asyncio.DatagramTransport) -> None:
    self.transport = transport

  def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
    self.queue.put_nowait(data)

  def error_received(self, exc: Exception) -> None:
    pass

  def connection_lost(self, exc: Optional[Exception]) -> None:
    pass


class A2SAdapter:
  """Pure asyncio Steam A2S_INFO query client with caching and challenge negotiation."""

  def __init__(
      self,
      cache_ttl: float = TIMING_CONFIG.a2s_cache_ttl,
      query_timeout: float = TIMING_CONFIG.a2s_timeout,
      call_tracker: Optional[CallTrackerProtocol] = None,
  ):
    self.cache_ttl = cache_ttl
    self.query_timeout = query_timeout
    self.call_tracker = call_tracker
    self._cache: dict[str, dict] = {}

  def _parse_a2s_response(self, data: bytes) -> Optional[dict]:
    if len(data) < 5 or data[:4] != b"\xff\xff\xff\xff":
      return None
    header = data[4:5]

    if header == b"\x41" and len(data) >= 9:
      return {"challenge": data[5:9]}

    if header == b"\x49":
      idx = 5
      if idx >= len(data):
        return None
      idx += 1

      def read_cstring(b: bytes, offset: int) -> Tuple[str, int]:
        end = b.find(b"\x00", offset)
        if end == -1:
          return "", len(b)
        return b[offset:end].decode("utf-8", errors="replace"), end + 1

      _, idx = read_cstring(data, idx)
      _, idx = read_cstring(data, idx)
      _, idx = read_cstring(data, idx)
      _, idx = read_cstring(data, idx)

      idx += 2
      if idx + 2 > len(data):
        return None

      players = data[idx]
      max_players = data[idx + 1]
      return {"players": players, "max_players": max_players}

    return None

  async def get_player_count(
      self, host: str, port: int
  ) -> Tuple[Optional[int], Optional[int]]:
    if not host or not port or port <= 0:
      return None, None

    cache_key = f"{host}:{port}"
    now = time.time()
    cached = self._cache.get(cache_key)
    if cached and cached["expires"] > now:
      return cached["players"], cached["max_players"]

    start_time = time.time()
    loop = asyncio.get_running_loop()
    try:
      transport, protocol = await loop.create_datagram_endpoint(
          lambda: A2SProtocol(), remote_addr=(host, port)
      )
    except Exception:
      if self.call_tracker:
        self.call_tracker.record(
            endpoint="Steam A2S: Query (UDP)",
            method="UDP",
            status="ERR",
            duration_ms=(time.time() - start_time) * 1000,
            details=f"{host}:{port}",
        )
      return None, None

    try:
      transport.sendto(A2S_INFO_REQUEST)
      resp_data = await asyncio.wait_for(
          protocol.queue.get(), timeout=self.query_timeout
      )
      parsed = self._parse_a2s_response(resp_data)

      if parsed and "challenge" in parsed:
        challenge_req = A2S_INFO_REQUEST + parsed["challenge"]
        transport.sendto(challenge_req)
        resp_data2 = await asyncio.wait_for(
            protocol.queue.get(), timeout=self.query_timeout
        )
        parsed = self._parse_a2s_response(resp_data2)

      if parsed and "players" in parsed:
        players, max_players = parsed["players"], parsed["max_players"]
        self._cache[cache_key] = {
            "players": players,
            "max_players": max_players,
            "expires": now + self.cache_ttl,
        }
        if self.call_tracker:
          self.call_tracker.record(
              endpoint="Steam A2S: Query (UDP)",
              method="UDP",
              status="200",
              duration_ms=(time.time() - start_time) * 1000,
              details=f"{host}:{port} ({players}/{max_players} players)",
          )
        return players, max_players
    except Exception:
      self._cache[cache_key] = {
          "players": None,
          "max_players": None,
          "expires": now + 10.0,
      }
      if self.call_tracker:
        self.call_tracker.record(
            endpoint="Steam A2S: Query (UDP)",
            method="UDP",
            status="TIMEOUT",
            duration_ms=(time.time() - start_time) * 1000,
            details=f"{host}:{port}",
        )
    finally:
      transport.close()

    return None, None