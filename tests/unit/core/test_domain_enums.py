import unittest

from app.core.models import (
    PowerState,
    ServerStatusDTO,
    ServerUpdateStatus,
)


class TestServerUpdateStatusEnum(unittest.TestCase):

  def test_server_update_status_values_and_identity(self):
    self.assertEqual(ServerUpdateStatus.UP_TO_DATE, "Up to date")
    self.assertEqual(ServerUpdateStatus.UPDATE_AVAILABLE, "Update Available")
    self.assertEqual(ServerUpdateStatus.COUNTDOWN_ACTIVE, "Update Available (Countdown Active)")
    self.assertEqual(ServerUpdateStatus.RESTART_DISPATCHED, "Restart dispatched — waiting for build update")
    self.assertEqual(ServerUpdateStatus.IDLE, "Idle")
    self.assertEqual(ServerUpdateStatus.ERROR, "Error")

    self.assertEqual(
        {s.value for s in ServerUpdateStatus},
        {
            "Up to date",
            "Update Available",
            "Update Available (Countdown Active)",
            "Restart dispatched — waiting for build update",
            "Idle",
            "Error",
        },
    )

  def test_server_update_status_string_inheritance(self):
    self.assertIsInstance(ServerUpdateStatus.UP_TO_DATE, str)
    self.assertIsInstance(ServerUpdateStatus.UPDATE_AVAILABLE, str)
    self.assertEqual(f"{ServerUpdateStatus.UP_TO_DATE}", "Up to date")
    self.assertEqual(str(ServerUpdateStatus.COUNTDOWN_ACTIVE), "Update Available (Countdown Active)")

  def test_server_update_status_from_str_normalization(self):
    # Direct match (case insensitive)
    self.assertIs(ServerUpdateStatus.from_str(ServerUpdateStatus.UP_TO_DATE), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("Up to date"), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("UP TO DATE"), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("  up to date  "), ServerUpdateStatus.UP_TO_DATE)
    self.assertIs(ServerUpdateStatus.from_str("Update Available"), ServerUpdateStatus.UPDATE_AVAILABLE)
    self.assertIs(ServerUpdateStatus.from_str("Idle"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Error"), ServerUpdateStatus.ERROR)

    # Partial / Legacy fuzzy matches
    self.assertIs(ServerUpdateStatus.from_str("Manual offline — countdown cancelled"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Countdown cancelled (restart requested)"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Test mode disabled — countdown cancelled"), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("Update Available — Countdown Started"), ServerUpdateStatus.COUNTDOWN_ACTIVE)
    self.assertIs(ServerUpdateStatus.from_str("Restarting server via Pterodactyl API..."), ServerUpdateStatus.RESTART_DISPATCHED)
    self.assertIs(ServerUpdateStatus.from_str("waiting for build update"), ServerUpdateStatus.RESTART_DISPATCHED)
    self.assertIs(ServerUpdateStatus.from_str("Error: Failed to fetch build"), ServerUpdateStatus.ERROR)
    self.assertIs(ServerUpdateStatus.from_str("Connection failed"), ServerUpdateStatus.ERROR)

    # Empty and unknown fallback to IDLE
    self.assertIs(ServerUpdateStatus.from_str(None), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str(""), ServerUpdateStatus.IDLE)
    self.assertIs(ServerUpdateStatus.from_str("unknown_xyz"), ServerUpdateStatus.IDLE)

  def test_server_status_dto_accepts_enum_and_str(self):
    dto = ServerStatusDTO(
        idx=0,
        server_id="srv1",
        name="Server 1",
        power_state=PowerState.RUNNING,
        current_build="100",
        latest_build="200",
        last_status=ServerUpdateStatus.UPDATE_AVAILABLE,
        target_timestamp=0.0,
        remaining_seconds=0,
        is_updating=True,
    )
    self.assertEqual(dto.last_status, ServerUpdateStatus.UPDATE_AVAILABLE)
    self.assertEqual(dto.last_status, "Update Available")

    dumped = dto.model_dump()
    self.assertEqual(dumped["last_status"], "Update Available")


if __name__ == "__main__":
  unittest.main()
