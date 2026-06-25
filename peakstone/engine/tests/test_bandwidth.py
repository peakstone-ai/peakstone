"""Bandwidth sample store + median estimate."""
from __future__ import annotations

from peakstone.engine import bandwidth


def test_record_and_median(tmp_path):
    p = tmp_path / "bw.json"
    assert bandwidth.estimated_mbps(p) is None              # no data yet
    bandwidth.record(100 * 1e6, 10, "hf", path=p)          # 10 MB/s
    bandwidth.record(300 * 1e6, 10, "docker", path=p)      # 30 MB/s
    bandwidth.record(200 * 1e6, 10, "hf", path=p)          # 20 MB/s
    assert bandwidth.estimated_mbps(p) == 20.0             # median


def test_record_ignores_degenerate(tmp_path):
    p = tmp_path / "bw.json"
    bandwidth.record(0, 10, "x", path=p)
    bandwidth.record(1e6, 0, "x", path=p)
    assert bandwidth.estimated_mbps(p) is None
