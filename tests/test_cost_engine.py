"""Unit tests for MinuteMeter's pure cost computation (no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import minutemeter as mm  # noqa: E402
import rates  # noqa: E402


def test_detect_runner_standard_linux():
    assert mm.detect_runner(["ubuntu-latest"]) == ("linux", 2, False)


def test_detect_runner_windows_macos():
    assert mm.detect_runner(["windows-latest"])[0] == "windows"
    assert mm.detect_runner(["macos-latest"])[0] == "macos"


def test_detect_runner_self_hosted():
    os_name, cores, self_hosted = mm.detect_runner(
        ["self-hosted", "linux", "x64"], "my-runner-7"
    )
    assert self_hosted is True
    assert os_name == "linux"


def test_detect_runner_larger():
    os_name, cores, self_hosted = mm.detect_runner(["ubuntu-latest-8-cores"])
    assert (os_name, cores, self_hosted) == ("linux", 8, False)


def test_billable_minutes_rounds_up():
    assert mm.billable_minutes(0) == 0
    assert mm.billable_minutes(1) == 1
    assert mm.billable_minutes(60) == 1
    assert mm.billable_minutes(61) == 2
    assert mm.billable_minutes(599) == 10


def test_rate_table():
    assert rates.rate_per_minute("linux") == 0.006
    assert rates.rate_per_minute("windows") == 0.010
    assert rates.rate_per_minute("macos") == 0.062
    assert rates.rate_per_minute("linux", self_hosted=True) == 0.002
    assert rates.rate_per_minute("linux", cores=8) == 0.022


def test_compute_job_cost_linux():
    job = {
        "name": "build",
        "labels": ["ubuntu-latest"],
        "started_at": "2026-06-14T01:00:00Z",
        "completed_at": "2026-06-14T01:05:00Z",  # 5 min
    }
    r = mm.compute_job_cost(job)
    assert r["minutes"] == 5
    assert r["cost"] == round(5 * 0.006, 4)  # 0.03


def test_compute_job_cost_self_hosted_rounds_up():
    job = {
        "name": "deploy",
        "labels": ["self-hosted", "linux"],
        "started_at": "2026-06-14T01:00:00Z",
        "completed_at": "2026-06-14T01:04:30Z",  # 4.5 min -> 5
    }
    r = mm.compute_job_cost(job)
    assert r["self_hosted"] is True
    assert r["minutes"] == 5
    assert r["cost"] == round(5 * 0.002, 4)  # 0.01


def test_compute_run_sorts_and_totals():
    jobs = [
        {"name": "cheap", "labels": ["ubuntu-latest"],
         "started_at": "2026-06-14T01:00:00Z", "completed_at": "2026-06-14T01:01:00Z"},
        {"name": "pricey", "labels": ["macos-latest"],
         "started_at": "2026-06-14T01:00:00Z", "completed_at": "2026-06-14T01:10:00Z"},
    ]
    result = mm.compute_run(jobs)
    assert result["jobs"][0]["name"] == "pricey"  # sorted by cost desc
    assert result["total_minutes"] == 11
    assert result["total_cost"] == round(0.006 + 10 * 0.062, 4)


def test_render_markdown_has_marker_and_budget_flag():
    result = mm.compute_run([
        {"name": "build", "labels": ["macos-latest"],
         "started_at": "2026-06-14T01:00:00Z", "completed_at": "2026-06-14T01:10:00Z"},
    ])
    body = mm.render_markdown(result, "owner/repo", "123", budget_usd=0.10)
    assert mm.COMMENT_MARKER in body
    assert "OVER" in body  # 10 * 0.062 = 0.62 > 0.10
    assert "owner/repo" in body


def test_missing_timestamps_zero_cost():
    r = mm.compute_job_cost({"name": "skipped", "labels": ["ubuntu-latest"]})
    assert r["minutes"] == 0
    assert r["cost"] == 0
