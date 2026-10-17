import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.adapters.a2s import A2SAdapter, A2S_INFO_REQUEST
from app.core.models import PlayerMetrics


class TestA2SAdapterDatagram(unittest.IsolatedAsyncioTestCase):

  def setUp(self):
    self.adapter = A2SAdapter()

  def test_parse_a2s_response_valid_info_packet(self):
    # Construct synthetic A2S_INFO packet
    data = (
        b"\xff\xff\xff\xff\x49"  # Header (0xFFFFFFFF) + Type (0x49)
        b"\x11"                  # Protocol version 17
        b"Valheim Dedicated Server\x00"  # Name
        b"Dedicated\x00"                 # Map
        b"valheim\x00"                   # Folder
        b"Valheim\x00"                   # Game
        b"\x88\x13"                      # Steam AppID (5000)
        + bytes([8, 64])                 # Players (8), Max Players (64)
    )
    parsed = self.adapter._parse_a2s_response(data)
    self.assertIsNotNone(parsed)
    self.assertEqual(parsed["players"], 8)
    self.assertEqual(parsed["max_players"], 64)

  def test_parse_a2s_response_challenge_packet(self):
    data = b"\xff\xff\xff\xff\x41\x11\x22\x33\x44"
    parsed = self.adapter._parse_a2s_response(data)
    self.assertIsNotNone(parsed)
    self.assertEqual(parsed["challenge"], b"\x11\x22\x33\x44")

  def test_parse_a2s_response_invalid_packets(self):
    # Too short
    self.assertIsNone(self.adapter._parse_a2s_response(b"\x00\x00"))
    # Wrong magic header
    self.assertIsNone(self.adapter._parse_a2s_response(b"\x01\x02\x03\x04\x49"))
    # Unknown type byte
    self.assertIsNone(self.adapter._parse_a2s_response(b"\xff\xff\xff\xff\x99"))

  async def test_get_player_count_invalid_arguments_returns_none(self):
    res = await self.adapter.get_player_count("", 0)
    self.assertEqual(res, PlayerMetrics(None, None))
    res2 = await self.adapter.get_player_count("127.0.0.1", -5)
    self.assertEqual(res2, PlayerMetrics(None, None))

  async def test_get_player_count_with_challenge_resend(self):
    mock_transport = MagicMock()
    mock_protocol = MagicMock()
    mock_protocol.queue = asyncio.Queue()

    # 1st response: Challenge request (0x41)
    mock_protocol.queue.put_nowait(b"\xff\xff\xff\xff\x41\xaa\xbb\xcc\xdd")

    # 2nd response: Valid info response (0x49) with 15 players of 32
    info_packet = (
        b"\xff\xff\xff\xff\x49\x11"
        b"My Palworld\x00"
        b"World\x00"
        b"Pal\x00"
        b"Palworld\x00"
        b"\x00\x00"
        + bytes([15, 32])
    )
    mock_protocol.queue.put_nowait(info_packet)

    loop = asyncio.get_running_loop()
    with patch.object(
        loop,
        "create_datagram_endpoint",
        new=AsyncMock(return_value=(mock_transport, mock_protocol)),
    ):
      metrics = await self.adapter.get_player_count("1.2.3.4", 27015)
      self.assertEqual(metrics.current, 15)
      self.assertEqual(metrics.max, 32)

      # Verify challenge resend occurred
      self.assertEqual(mock_transport.sendto.call_count, 2)
      expected_second_call = A2S_INFO_REQUEST + b"\xaa\xbb\xcc\xdd"
      mock_transport.sendto.assert_called_with(expected_second_call)


if __name__ == "__main__":
  unittest.main()
