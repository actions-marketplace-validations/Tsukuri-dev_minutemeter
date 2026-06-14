#!/usr/bin/env python3
"""MinuteMeter — GitHub Actions cost attribution.

Reads a workflow run's jobs, attributes a USD cost to each job from the runner
rate table, and posts a per-job breakdown as a PR comment + job summary.

Pure computation (detect_runner / cost helpers / render_markdown) is separated
from I/O (gh_api / fetch / upsert) so the cost logic is unit-testable offline.
Stdlib only — no pip install, runs on any runner with Python 3.

Required scope: actions:read (run/jobs), pull-requests:write (comment).
"""
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request

try:
    from . import rates
except ImportError:  # run as a script (no package context)
    import rates

API = "https://api.github.com"
COMMENT_MARKER = "<!-- minutemeter:cost-report -->"

# ---------------------------------------------------------------------------
# Pure computation (unit-testable, no network)
# ---------------------------------------------------------------------------

_CORE_RE = re.compile(r"(\d+)\s*-?\s*core", re.IGNORECASE)


def detect_runner(labels, runner_name=""):
    """Infer (os_name, cores, self_hosted) from a job's labels/runner_name.

    labels: list like ["ubuntu-latest"] or ["self-hosted","linux","x64"].
    """
    labels = [str(l).lower() for l in (labels or [])]
    blob = " ".join(labels)
    self_hosted = "self-hosted" in labels or "self-hosted" in blob

    if "windows" in blob or "win" in blob:
        os_name = "windows"
    elif "macos" in blob or "mac" in blob or "osx" in blob:
        os_name = "macos"
    else:
        os_name = "linux"  # default; ubuntu/linux and unknowns map here

    cores = rates.DEFAULT_CORES
    m = _CORE_RE.search(blob)
    if m:
        cores = int(m.group(1))
    return os_name, cores, self_hosted


def billable_minutes(duration_seconds):
    """GitHub bills per started minute (round up). Negative/None -> 0."""
    if not duration_seconds or duration_seconds < 0:
        return 0
    return int(math.ceil(duration_seconds / 60.0))


def _duration_seconds(started_at, completed_at):
    """Wall-clock seconds between two ISO-8601 timestamps (Z-suffixed)."""
    if not started_at or not completed_at:
        return 0
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    from datetime import datetime
    try:
        a = datetime.strptime(started_at, fmt)
        b = datetime.strptime(completed_at, fmt)
    except ValueError:
        return 0
    return max(0, int((b - a).total_seconds()))


def compute_job_cost(job):
    """Attribute a USD cost to one job dict (from the /jobs API).

    Returns {name, os, cores, self_hosted, minutes, rate, cost}.
    """
    os_name, cores, self_hosted = detect_runner(
        job.get("labels"), job.get("runner_name", "")
    )
    seconds = _duration_seconds(job.get("started_at"), job.get("completed_at"))
    minutes = billable_minutes(seconds)
    rate = rates.rate_per_minute(os_name, cores, self_hosted)
    return {
        "name": job.get("name", "?"),
        "os": os_name,
        "cores": cores,
        "self_hosted": self_hosted,
        "minutes": minutes,
        "rate": rate,
        "cost": round(minutes * rate, 4),
    }


def compute_run(jobs):
    """Compute per-job costs + totals for a list of job dicts."""
    rows = [compute_job_cost(j) for j in jobs]
    rows.sort(key=lambda r: r["cost"], reverse=True)
    total_cost = round(sum(r["cost"] for r in rows), 4)
    total_minutes = sum(r["minutes"] for r in rows)
    return {"jobs": rows, "total_cost": total_cost, "total_minutes": total_minutes}


def render_markdown(result, repo, run_id, budget_usd=None, top_n=15):
    """Render the cost breakdown as a Markdown comment body."""
    rows = result["jobs"]
    lines = [
        COMMENT_MARKER,
        "### 💸 MinuteMeter — GitHub Actions cost",
        "",
        f"**Run total: ${result['total_cost']:.4f}** "
        f"({result['total_minutes']} billable min) "
        f"· [run](https://github.com/{repo}/actions/runs/{run_id})",
        "",
    ]
    over = budget_usd is not None and result["total_cost"] > budget_usd
    if budget_usd is not None:
        flag = "🔴 OVER" if over else "🟢 ok"
        lines.append(f"**Budget ${budget_usd:.2f}/run: {flag}**")
        lines.append("")
    lines += ["| Job | Runner | Min | $ |", "|---|---|--:|--:|"]
    for r in rows[:top_n]:
        runner = ("self-hosted " if r["self_hosted"] else "") + r["os"]
        if r["cores"] != rates.DEFAULT_CORES:
            runner += f" {r['cores']}c"
        lines.append(f"| {r['name']} | {runner} | {r['minutes']} | ${r['cost']:.4f} |")
    if len(rows) > top_n:
        lines.append(f"| … +{len(rows) - top_n} more | | | |")
    lines += ["", "<sub>GitHub list prices, billed per started minute, gross of included "
              "free minutes. Self-hosted shown free (the announced charge was shelved). "
              "Heads up: Copilot code review also consumes Actions minutes from this pool.</sub>"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O (network) — thin wrappers over the GitHub REST API
# ---------------------------------------------------------------------------

def gh_api(method, path, token, body=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def fetch_jobs(repo, run_id, token):
    """All jobs for a run (paginated)."""
    jobs, page = [], 1
    while True:
        data = gh_api(
            "GET",
            f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}",
            token,
        )
        batch = data.get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


def upsert_pr_comment(repo, pr_number, token, body):
    """Create or update the single MinuteMeter comment on a PR (idempotent)."""
    existing = gh_api(
        "GET", f"/repos/{repo}/issues/{pr_number}/comments?per_page=100", token
    )
    for c in existing:
        if COMMENT_MARKER in (c.get("body") or ""):
            gh_api("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", token,
                   {"body": body})
            return "updated"
    gh_api("POST", f"/repos/{repo}/issues/{pr_number}/comments", token,
           {"body": body})
    return "created"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_event():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _resolve_run_id(event):
    return (
        os.environ.get("INPUT_RUN_ID")
        or str(event.get("workflow_run", {}).get("id") or "")
        or os.environ.get("GITHUB_RUN_ID", "")
    )


def _resolve_pr(event):
    if os.environ.get("INPUT_PR_NUMBER"):
        return os.environ["INPUT_PR_NUMBER"]
    if event.get("pull_request"):
        return str(event["pull_request"]["number"])
    prs = event.get("workflow_run", {}).get("pull_requests") or []
    if prs:
        return str(prs[0]["number"])
    return None


def _write_summary(body):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(body + "\n")


def main():
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("::error::GITHUB_TOKEN and GITHUB_REPOSITORY are required")
        return 1
    event = _load_event()
    run_id = _resolve_run_id(event)
    if not run_id:
        print("::error::could not resolve a run id to analyze")
        return 1
    budget = os.environ.get("INPUT_BUDGET_USD")
    budget = float(budget) if budget else None

    try:
        jobs = fetch_jobs(repo, run_id, token)
    except urllib.error.HTTPError as e:
        # Never fail the CI run on a non-fatal API problem (DoD: graceful).
        print(f"::warning::MinuteMeter could not fetch jobs ({e.code}); skipping")
        return 0

    result = compute_run(jobs)
    body = render_markdown(result, repo, run_id, budget_usd=budget)
    _write_summary(body)

    pr = _resolve_pr(event)
    if pr:
        try:
            action = upsert_pr_comment(repo, pr, token, body)
            print(f"MinuteMeter comment {action} on PR #{pr}")
        except urllib.error.HTTPError as e:
            print(f"::warning::MinuteMeter could not post comment ({e.code})")
    else:
        print("MinuteMeter: no PR context; wrote job summary only")

    print(f"::notice::MinuteMeter run total ${result['total_cost']:.4f} "
          f"({result['total_minutes']} min, {len(result['jobs'])} jobs)")
    if budget is not None and result["total_cost"] > budget:
        print(f"::warning::Run cost ${result['total_cost']:.4f} exceeds "
              f"budget ${budget:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
