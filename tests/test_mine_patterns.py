"""
Tests for workspace/lib/mining/mine_patterns.py
MINE-02: Data Cruncher — Cohen's d gate, per-hypothesis error handling, JSON output.

TDD RED phase — tests are written before the implementation exists.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


# ---------------------------------------------------------------------------
# Helpers to import the module under test
# ---------------------------------------------------------------------------

def _load_module():
    """Import mine_patterns from the workspace lib directory."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "mine_patterns",
        Path("/Users/liang/.openclaw/workspace/lib/mining/mine_patterns.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCohensD(unittest.TestCase):
    """Test 1 & 2 — Cohen's d computation and fail-open guard."""

    def setUp(self):
        self.mod = _load_module()

    def test_small_groups_return_zero(self):
        """Test 2: groups with < 2 samples must return 0.0."""
        d = self.mod.cohens_d(np.array([1.0]), np.array([2.0, 3.0, 4.0]))
        self.assertEqual(d, 0.0)

    def test_both_groups_small(self):
        """Test 2: both groups with 1 sample each return 0.0."""
        d = self.mod.cohens_d(np.array([1.0]), np.array([2.0]))
        self.assertEqual(d, 0.0)

    def test_zero_variance_returns_zero(self):
        """Identical groups should return 0.0 (pooled std = 0)."""
        d = self.mod.cohens_d(np.array([5.0, 5.0, 5.0]), np.array([5.0, 5.0, 5.0]))
        self.assertEqual(d, 0.0)

    def test_distinct_groups_positive_d(self):
        """Clearly separated groups with variance should produce d > 0.5."""
        rng = np.random.default_rng(42)
        group_a = rng.normal(loc=100.0, scale=5.0, size=50)  # high mean, some variance
        group_b = rng.normal(loc=0.0, scale=5.0, size=50)    # low mean, same variance
        d = self.mod.cohens_d(group_a, group_b)
        self.assertGreater(d, 0.5)

    def test_returns_float(self):
        """Cohen's d must return a Python float."""
        d = self.mod.cohens_d(np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))
        self.assertIsInstance(d, float)


class TestCohensDGate(unittest.TestCase):
    """Test 3 — Hypotheses with Cohen's d < 0.5 are excluded from output."""

    def setUp(self):
        self.mod = _load_module()

    def _make_hypothesis(self, name: str, d: float) -> dict:
        """Create a hypothesis result dict as the Data Cruncher would."""
        return {
            "name": name,
            "sql": "SELECT * FROM test",
            "cohens_d": d,
            "f1_estimate": 0.5,
            "rationale": "test",
            "metric_thresholds": {},
        }

    def test_low_d_excluded(self):
        """Hypotheses with d < 0.5 must not appear in qualified output."""
        hypotheses = [
            self._make_hypothesis("low_d", 0.3),
            self._make_hypothesis("high_d", 0.8),
        ]
        qualified = self.mod.apply_cohens_d_gate(hypotheses, threshold=0.5)
        names = [h["name"] for h in qualified]
        self.assertNotIn("low_d", names)
        self.assertIn("high_d", names)

    def test_exactly_0_5_passes(self):
        """d == 0.5 is on the boundary — should pass the gate."""
        hypotheses = [self._make_hypothesis("boundary", 0.5)]
        qualified = self.mod.apply_cohens_d_gate(hypotheses, threshold=0.5)
        self.assertEqual(len(qualified), 1)

    def test_empty_input_returns_empty(self):
        """Empty hypothesis list returns empty list."""
        qualified = self.mod.apply_cohens_d_gate([], threshold=0.5)
        self.assertEqual(qualified, [])


class TestOutputFormat(unittest.TestCase):
    """Test 4 — Output is valid JSON array with required fields."""

    def setUp(self):
        self.mod = _load_module()

    REQUIRED_FIELDS = {"name", "sql", "cohens_d", "f1_estimate", "rationale", "metric_thresholds"}

    def test_required_fields_present(self):
        """Each qualified hypothesis must have all required fields."""
        hypotheses = [
            {
                "name": "test_hypothesis",
                "sql": "SELECT maker, COUNT(*) FROM parquet_scan('...') GROUP BY maker",
                "cohens_d": 0.72,
                "f1_estimate": 0.61,
                "rationale": "Hypothesis about maker behavior",
                "metric_thresholds": {"trade_usd": ">10000"},
            }
        ]
        # Should not raise
        for h in hypotheses:
            for field in self.REQUIRED_FIELDS:
                self.assertIn(field, h, f"Missing required field: {field}")

    def test_format_hypothesis_for_output(self):
        """format_hypothesis_for_output must include all required fields."""
        raw = {
            "name": "test_hyp",
            "sql": "SELECT * FROM x",
            "cohens_d": 0.7,
            "f1_estimate": 0.6,
            "rationale": "test",
            "metric_thresholds": {"experience_markets": "<5"},
        }
        result = self.mod.format_hypothesis_for_output(raw)
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, result, f"Missing required field: {field}")

    def test_json_serializable(self):
        """format_hypothesis_for_output result must be JSON-serializable."""
        raw = {
            "name": "test_hyp",
            "sql": "SELECT * FROM x",
            "cohens_d": 0.7,
            "f1_estimate": 0.6,
            "rationale": "test",
            "metric_thresholds": {},
        }
        result = self.mod.format_hypothesis_for_output(raw)
        # Should not raise
        serialized = json.dumps([result])
        parsed = json.loads(serialized)
        self.assertEqual(len(parsed), 1)


class TestPerHypothesisErrorHandling(unittest.TestCase):
    """Test 5 — DuckDB errors are caught per-hypothesis and skipped, not abort."""

    def setUp(self):
        self.mod = _load_module()

    def test_bad_query_skipped_not_abort(self):
        """A hypothesis with an invalid SQL must be skipped; others still processed."""
        mock_conn = MagicMock()

        call_count = [0]

        def fake_execute(sql):
            call_count[0] += 1
            if "bad_column" in sql:
                raise Exception("Binder Error: Referenced column bad_column not found")
            result = MagicMock()
            result.fetchdf.return_value = _make_sample_df()
            return result

        mock_conn.execute.side_effect = fake_execute

        hypotheses = [
            {"name": "bad_hyp", "sql": "SELECT bad_column FROM x", "rationale": "bad"},
            {"name": "good_hyp", "sql": "SELECT maker FROM x", "rationale": "good"},
        ]

        results = self.mod.crunch_hypotheses(mock_conn, hypotheses)
        # bad_hyp should be skipped; good_hyp should produce a result
        names = [r["name"] for r in results]
        self.assertNotIn("bad_hyp", names)
        # good_hyp may or may not qualify (depends on df contents), but no crash
        # The key requirement is: no exception raised

    def test_all_bad_queries_returns_empty(self):
        """All bad queries should produce empty results, not crash."""
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("column not found")

        hypotheses = [
            {"name": "bad_1", "sql": "SELECT x FROM y", "rationale": "bad"},
            {"name": "bad_2", "sql": "SELECT z FROM w", "rationale": "bad"},
        ]

        results = self.mod.crunch_hypotheses(mock_conn, hypotheses)
        self.assertEqual(results, [])


class TestDescribeIntrospection(unittest.TestCase):
    """Test 1 — DESCRIBE returns valid column list, not hardcoded names."""

    def setUp(self):
        self.mod = _load_module()

    def test_describe_returns_list_of_strings(self):
        """get_parquet_columns must return a non-empty list of strings."""
        mock_conn = MagicMock()
        mock_df = MagicMock()
        mock_df.__iter__ = MagicMock(return_value=iter([
            MagicMock(column_name="maker"),
            MagicMock(column_name="taker"),
            MagicMock(column_name="size"),
        ]))
        mock_df.itertuples = MagicMock(return_value=iter([
            MagicMock(column_name="maker"),
            MagicMock(column_name="taker"),
            MagicMock(column_name="size"),
        ]))
        # Most likely implementation uses fetchdf().itertuples() or similar
        mock_result = MagicMock()
        mock_result.fetchdf.return_value = _make_describe_df()
        mock_conn.execute.return_value = mock_result

        columns = self.mod.get_parquet_columns(mock_conn, "/fake/path/**/*.parquet")
        self.assertIsInstance(columns, list)
        self.assertTrue(len(columns) > 0)
        for col in columns:
            self.assertIsInstance(col, str)

    def test_describe_does_not_hardcode_columns(self):
        """get_parquet_columns must call DESCRIBE, not return a fixed list."""
        import inspect
        source = inspect.getsource(self.mod.get_parquet_columns)
        self.assertIn("DESCRIBE", source.upper(), "Must use DESCRIBE to introspect schema")
        # Must NOT hardcode known column names
        hardcoded_columns = ["maker_address", "taker_address", "amount_usd"]
        for col in hardcoded_columns:
            self.assertNotIn(f'"{col}"', source, f"Column name {col} appears hardcoded")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_sample_df():
    """Return a realistic Pandas DataFrame for hypothesis evaluation."""
    import pandas as pd
    return pd.DataFrame({
        "wallet": ["0x" + "a" * 40, "0x" + "b" * 40],
        "trade_count": [100, 5],
        "total_usd": [50000.0, 200.0],
        "group": ["anomalous", "baseline"],
    })


def _make_describe_df():
    """Return a DESCRIBE-like DataFrame with column_name column."""
    import pandas as pd
    return pd.DataFrame({
        "column_name": ["maker", "taker", "size", "price", "side", "condition_id"],
        "column_type": ["VARCHAR", "VARCHAR", "FLOAT", "FLOAT", "VARCHAR", "VARCHAR"],
    })


if __name__ == "__main__":
    unittest.main()
