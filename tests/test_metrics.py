import os
import sys
import unittest


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(ROOT_DIR, 'scripts')
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from metrics import (
    classify_risk,
    compute_availability_stats,
    ewma_forecast,
    moving_average,
    risk_score,
)
from log_processor import parse_log_lines


class MetricsTest(unittest.TestCase):
    def test_moving_average_uses_last_window(self):
        self.assertAlmostEqual(moving_average([1.0, 1.0, 0.6, 0.2, 0.0, 1.0], 3), 0.4)

    def test_ewma_forecast_reacts_to_recent_drop(self):
        values = [1.0, 1.0, 1.0, 0.2]
        self.assertLess(ewma_forecast(values, alpha=0.5), moving_average(values, 3))

    def test_risk_classification_is_score_based(self):
        self.assertEqual(classify_risk(0.10), 'LOW')
        self.assertEqual(classify_risk(0.30), 'MEDIUM')
        self.assertEqual(classify_risk(0.60), 'HIGH')

    def test_compute_availability_stats_contains_research_metrics(self):
        stats = compute_availability_stats([1.0, 0.6, 0.2, 1.0, 0.0])
        self.assertIn('ewma_prediction', stats)
        self.assertIn('availability_ci_low', stats)
        self.assertIn('risk_score', stats)
        self.assertGreaterEqual(stats['risk_score'], 0.0)
        self.assertLessEqual(stats['risk_score'], 1.0)

    def test_risk_score_grows_when_availability_degrades(self):
        stable = risk_score([1.0, 1.0, 1.0, 1.0])
        degraded = risk_score([1.0, 0.6, 0.2, 0.0])
        self.assertGreater(degraded, stable)


class LogParsingTest(unittest.TestCase):
    def test_parse_log_lines_prefers_event_timestamp_and_maps_level(self):
        line = (
            '172.27.0.1 - - [06/Jun/2026:23:11:10 +0000] '
            '"GET /api/logs?id=operator.test&level=ERROR&module=sofia.c'
            '&code=4590&message=SIP+503&evt_ts=2026-06-06T09%3A08%3A05.456 HTTP/1.1" '
            '200 0 "-" "python-requests/2.32.5"'
        )
        metrics = parse_log_lines([line])
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]['service_id'], 'operator.test')
        self.assertEqual(metrics[0]['availability'], 0.2)
        self.assertEqual(metrics[0]['ts'], '2026-06-06T09:08:05.456000')


if __name__ == '__main__':
    unittest.main()
