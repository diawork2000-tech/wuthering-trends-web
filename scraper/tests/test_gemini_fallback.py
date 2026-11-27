import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intelligence_collector as ic


class FakeModels:
    def __init__(self, fail):
        self.fail, self.calls = fail, []

    def generate_content(self, model, contents):
        self.calls.append(model)
        err = self.fail.get(model)
        if err:
            raise RuntimeError(err)
        return mock.Mock(text="[]")


def engine(fail):
    e = ic.IntelligenceEngine.__new__(ic.IntelligenceEngine)
    e.gemini_model_name = "gemini-flash-latest"
    e.gemini_client = mock.Mock(models=FakeModels(fail))
    return e


class TestFallback(unittest.TestCase):
    @mock.patch.object(ic.time, "sleep")
    def test_busy_main_model_falls_back(self, _):
        e = engine({"gemini-flash-latest": "503 UNAVAILABLE"})
        e._generate_with_fallback("p", "Schedule")
        self.assertEqual(e.gemini_client.models.calls,
                         ["gemini-flash-latest", "gemini-flash-latest", "gemini-flash-lite-latest"])

    @mock.patch.object(ic.time, "sleep")
    def test_non_transient_skips_retry(self, _):
        e = engine({"gemini-flash-latest": "400 bad request"})
        e._generate_with_fallback("p", "Schedule")
        self.assertEqual(e.gemini_client.models.calls, ["gemini-flash-latest", "gemini-flash-lite-latest"])

    @mock.patch.object(ic.time, "sleep")
    def test_all_busy_raises(self, _):
        busy = "503 UNAVAILABLE"
        e = engine({"gemini-flash-latest": busy, "gemini-flash-lite-latest": busy, "gemini-3.5-flash": busy})
        with self.assertRaises(RuntimeError):
            e._generate_with_fallback("p", "Schedule")
        self.assertEqual(len(e.gemini_client.models.calls), 6)


if __name__ == "__main__":
    unittest.main()
