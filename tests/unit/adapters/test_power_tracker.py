import time
import unittest
from unittest.mock import patch

from app.adapters.power_tracker import PowerStateTracker
from app.core.config import TIMING_CONFIG
from app.core.models import PowerSignal, PowerState


class TestPowerStateTracker(unittest.TestCase):

  def setUp(self):
    self.tracker = PowerStateTracker()

  def test_default_state_is_unknown(self):
    self.assertIsNone(self.tracker.get_valid_cache("srv1"))
    state = self.tracker.filter_state("srv1", "unknown")
    self.assertEqual(state, "unknown")

  def test_register_signal_start_and_restart(self):
    now = time.time()
    with patch("time.time", return_value=now):
      state = self.tracker.register_signal("srv1", "start")
      self.assertEqual(state, "starting")
      self.assertEqual(self.tracker.get_valid_cache("srv1"), "starting")

      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["starting_since"], now)
      self.assertEqual(entry["startup_grace_until"], now + TIMING_CONFIG.startup_grace_duration)
      self.assertEqual(entry["restart_lockout_until"], 0.0)

    # Restart signal sets restart lockout
    with patch("time.time", return_value=now + 1.0):
      state = self.tracker.register_signal("srv1", "restart")
      self.assertEqual(state, "starting")
      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["restart_lockout_until"], now + 1.0 + TIMING_CONFIG.restart_lockout_duration)

  def test_register_signal_stop_and_kill(self):
    now = time.time()
    with patch("time.time", return_value=now):
      state = self.tracker.register_signal("srv1", "stop")
      self.assertEqual(state, "stopping")
      self.assertEqual(self.tracker.get_valid_cache("srv1"), "stopping")

      entry = self.tracker._get_entry("srv1")
      self.assertEqual(entry["stopping_since"], now)
      self.assertFalse(entry["stopped_during_start"])

    # If stopped while container was starting
    self.tracker._get_entry("srv1")["smoothed_state"] = "starting"
    with patch("time.time", return_value=now + 2.0):
      self.tracker.register_signal("srv1", "kill")
      entry = self.tracker._get_entry("srv1")
      self.assertTrue(entry["stopped_during_start"])

  def test_restart_lockout_suppresses_stale_running_reports(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "restart")

    # During lockout, raw "running" report is suppressed and smoothed to "starting"
    with patch("time.time", return_value=now + 5.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "starting")

    # Once lockout expires, raw "running" is accepted
    with patch("time.time", return_value=now + 20.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_stopping_transitions_to_offline_cleanly(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # While shutting down, container still reports stopping
    with patch("time.time", return_value=now + 5.0):
      filtered = self.tracker.filter_state("srv1", "stopping")
      self.assertEqual(filtered, "stopping")

    # Once Wings reports offline/stopped, transitions to offline
    with patch("time.time", return_value=now + 10.0):
      filtered = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(filtered, "offline")

  def test_aborted_start_stop_recovery_edge_case(self):
    now = time.time()
    self.tracker._get_entry("srv1")["smoothed_state"] = "starting"
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # Before aborted start grace (8s), still reports stopping
    with patch("time.time", return_value=now + 4.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "stopping")

    # After aborted start grace (8s), server ignored stop and continues running
    with patch("time.time", return_value=now + 12.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_stopping_timeout_recovery_after_max_duration(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "stop")

    # Exceeding MAX_STOPPING_DURATION (45s) while container remains running recovers to running
    with patch("time.time", return_value=now + 50.0):
      filtered = self.tracker.filter_state("srv1", "running")
      self.assertEqual(filtered, "running")

  def test_startup_grace_period_suppresses_spurious_offline_reports(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "start")

    # Within startup grace (30s), raw offline is smoothed to starting
    with patch("time.time", return_value=now + 10.0):
      filtered = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(filtered, "starting")

  def test_offline_confirmation_threshold(self):
    now = time.time()
    with patch("time.time", return_value=now):
      self.tracker.register_signal("srv1", "start")

    # Fast forward past startup grace (35s)
    with patch("time.time", return_value=now + 35.0):
      # 1st offline -> starting
      f1 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f1, "starting")
      # 2nd offline -> starting
      f2 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f2, "starting")
      # 3rd offline -> reached threshold (3) -> offline confirmed
      f3 = self.tracker.filter_state("srv1", "offline")
      self.assertEqual(f3, "offline")

  def test_wings_running_instant_transition_and_pop_just_started(self):
    self.tracker.register_signal("srv1", "start")
    self.assertFalse(self.tracker.pop_just_started("srv1"))

    filtered = self.tracker.filter_state("srv1", "running")
    self.assertEqual(filtered, "running")
    # Instant transition to Online triggers just_started
    self.assertTrue(self.tracker.pop_just_started("srv1"))
    # Second check returns False (consumed)
    self.assertFalse(self.tracker.pop_just_started("srv1"))

  def test_invalidate_cache(self):
    self.tracker.register_signal("srv1", "start")
    self.assertIsNotNone(self.tracker.get_valid_cache("srv1"))

    # Invalidate single server
    self.tracker.invalidate("srv1")
    self.assertIsNone(self.tracker.get_valid_cache("srv1"))

    # Invalidate all servers
    self.tracker.register_signal("srv2", "start")
    self.assertIsNotNone(self.tracker.get_valid_cache("srv2"))
    self.tracker.invalidate()
    self.assertIsNone(self.tracker.get_valid_cache("srv2"))

  def test_power_state_tracker_strenum_types(self):
    # register_signal with PowerSignal enum
    state = self.tracker.register_signal("srv1", PowerSignal.START)
    self.assertIsInstance(state, PowerState)
    self.assertIs(state, PowerState.STARTING)

    # get_valid_cache returns PowerState enum
    cached = self.tracker.get_valid_cache("srv1")
    self.assertIsInstance(cached, PowerState)
    self.assertIs(cached, PowerState.STARTING)

    # filter_state with PowerState enum
    filtered = self.tracker.filter_state("srv1", PowerState.RUNNING)
    self.assertIsInstance(filtered, PowerState)
    self.assertIs(filtered, PowerState.RUNNING)

    # filter_state with Wings "stopped" string maps to PowerState.OFFLINE
    self.tracker.register_signal("srv1", PowerSignal.STOP)
    filtered_offline = self.tracker.filter_state("srv1", "stopped")
    self.assertIsInstance(filtered_offline, PowerState)
    self.assertIs(filtered_offline, PowerState.OFFLINE)

    # filter_state with unexpected string maps to PowerState.UNKNOWN
    unknown_state = self.tracker.filter_state("new_server", "crashed_or_gibberish")
    self.assertIsInstance(unknown_state, PowerState)
    self.assertIs(unknown_state, PowerState.UNKNOWN)

  def test_power_state_tracker_rapid_consecutive_transitions(self):
    # Rapid sequence START -> STOP -> START within grace windows
    s1 = self.tracker.register_signal("srv_rapid", PowerSignal.START)
    self.assertIs(s1, PowerState.STARTING)

    s2 = self.tracker.register_signal("srv_rapid", PowerSignal.STOP)
    self.assertIs(s2, PowerState.STOPPING)
    self.assertTrue(self.tracker._get_entry("srv_rapid")["stopped_during_start"])

    s3 = self.tracker.register_signal("srv_rapid", PowerSignal.START)
    self.assertIs(s3, PowerState.STARTING)
    self.assertFalse(self.tracker._get_entry("srv_rapid")["stopped_during_start"])

    # Wings reports running -> transitions immediately to RUNNING with just_started flag
    f = self.tracker.filter_state("srv_rapid", PowerState.RUNNING)
    self.assertIs(f, PowerState.RUNNING)
    self.assertTrue(self.tracker.pop_just_started("srv_rapid"))

  def test_power_state_tracker_case_insensitivity_and_strings(self):
    # Uppercase string signals and statuses
    s_start = self.tracker.register_signal("srv_case", "START")
    self.assertIs(s_start, PowerState.STARTING)

    s_stop = self.tracker.register_signal("srv_case", "STOP")
    self.assertIs(s_stop, PowerState.STOPPING)

    # In STOPPING state, STOPPED transitions cleanly to OFFLINE
    f_stopped = self.tracker.filter_state("srv_case", "STOPPED")
    self.assertIs(f_stopped, PowerState.OFFLINE)

    s_kill = self.tracker.register_signal("srv_case", "KILL")
    self.assertIs(s_kill, PowerState.STOPPING)

    # Invalid signal string leaves state unchanged
    s_bad = self.tracker.register_signal("srv_case", "invalid_action")
    self.assertIs(s_bad, PowerState.STOPPING)


if __name__ == "__main__":
  unittest.main()
