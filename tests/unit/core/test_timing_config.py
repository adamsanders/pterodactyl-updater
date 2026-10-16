import unittest

from app.adapters.power_tracker import PowerStateTracker
from app.core.config import TIMING_CONFIG, TimingConfig
from app.services.countdown import CountdownManager


class TestTimingConfig(unittest.TestCase):

  def test_default_timing_constants(self):
    self.assertEqual(TIMING_CONFIG.http_timeout, 10.0)
    self.assertEqual(TIMING_CONFIG.a2s_timeout, 1.5)
    self.assertEqual(TIMING_CONFIG.a2s_cache_ttl, 30.0)
    self.assertEqual(TIMING_CONFIG.power_transitional_ttl, 1.0)
    self.assertEqual(TIMING_CONFIG.power_steady_ttl, 15.0)
    self.assertEqual(TIMING_CONFIG.default_countdown_stages, (15, 10, 5, 1))

  def test_compute_warning_schedule_default(self):
    schedule = TIMING_CONFIG.compute_warning_schedule()
    expected = [
        (15, 300),  # 15m -> 10m: sleep 5m (300s)
        (10, 300),  # 10m -> 5m:  sleep 5m (300s)
        (5, 240),   # 5m  -> 1m:  sleep 4m (240s)
        (1, 60),    # 1m  -> 0m:  sleep 1m (60s)
    ]
    self.assertEqual(schedule, expected)
    self.assertEqual(sum(s for _, s in schedule), 900)
    self.assertEqual(TIMING_CONFIG.total_duration_seconds(), 900)

  def test_compute_warning_schedule_custom(self):
    # 30-minute schedule
    schedule_30 = TimingConfig.compute_warning_schedule((30, 15, 5, 1))
    expected_30 = [
        (30, 900),  # 30m -> 15m (15m sleep)
        (15, 600),  # 15m -> 5m  (10m sleep)
        (5, 240),   # 5m  -> 1m  (4m sleep)
        (1, 60),    # 1m  -> 0m  (1m sleep)
    ]
    self.assertEqual(schedule_30, expected_30)
    self.assertEqual(sum(s for _, s in schedule_30), 1800)
    self.assertEqual(TimingConfig.total_duration_seconds((30, 15, 5, 1)), 1800)

    # 10-minute schedule
    schedule_10 = TimingConfig.compute_warning_schedule((10, 5, 1))
    expected_10 = [(10, 300), (5, 240), (1, 60)]
    self.assertEqual(schedule_10, expected_10)
    self.assertEqual(sum(s for _, s in schedule_10), 600)

    # Single stage
    schedule_single = TimingConfig.compute_warning_schedule((5,))
    self.assertEqual(schedule_single, [(5, 300)])
    self.assertEqual(TimingConfig.total_duration_seconds((5,)), 300)

    # Empty stage
    self.assertEqual(TimingConfig.compute_warning_schedule(()), [])
    self.assertEqual(TimingConfig.total_duration_seconds(()), 0)

  def test_compute_warning_schedule_sorts_unordered_input(self):
    schedule = TimingConfig.compute_warning_schedule((1, 15, 5, 10))
    expected = [(15, 300), (10, 300), (5, 240), (1, 60)]
    self.assertEqual(schedule, expected)

  def test_countdown_manager_default_duration_matches_timing_config(self):
    cm = CountdownManager()
    cm.start("srv_test")
    remaining = cm.get_remaining("srv_test")
    self.assertGreaterEqual(remaining, 898)
    self.assertLessEqual(remaining, 900)

  def test_power_tracker_defaults_match_timing_config(self):
    self.assertEqual(
        PowerStateTracker.TRANSITIONAL_CACHE_TTL,
        TIMING_CONFIG.power_transitional_ttl,
    )
    self.assertEqual(
        PowerStateTracker.STEADY_CACHE_TTL,
        TIMING_CONFIG.power_steady_ttl,
    )
    self.assertEqual(
        PowerStateTracker.STARTUP_GRACE_DURATION,
        TIMING_CONFIG.startup_grace_duration,
    )


if __name__ == "__main__":
  unittest.main()
