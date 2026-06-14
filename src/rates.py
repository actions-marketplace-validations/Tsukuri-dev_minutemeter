"""GitHub Actions per-minute runner rates (USD).

Source: GitHub official pricing, observed 2026-06-14.
  - self-hosted cloud platform charge: $0.002/min (effective 2026-03-01)
  - hosted standard: Linux 2c $0.006, Windows 2c $0.010, macOS $0.062
  - larger runners: see LARGER_* tables
Evidence (evidence_log claim_ids): 0efbde3d160f, 539e5a1a4dc9, 8abe2b558752.

These are constants that GitHub may change; keep them in one place so a price
revision is a single-file edit. Prices are USD per billable minute.
"""

# Standard GitHub-hosted runners (2-core default), by OS.
STANDARD = {
    "linux": 0.006,
    "windows": 0.010,
    "macos": 0.062,
}

# Self-hosted runners: flat per-minute cloud platform charge (from 2026-03-01).
SELF_HOSTED = 0.002

# Larger GitHub-hosted runners, by OS and core count (x64).
LARGER = {
    "linux": {4: 0.012, 8: 0.022, 16: 0.042, 32: 0.082, 64: 0.162},
    "windows": {2: 0.010, 4: 0.022, 8: 0.042, 16: 0.082, 32: 0.162, 64: 0.322},
    "macos": {},  # macOS larger runners priced per-tier; fall back to STANDARD["macos"].
}

# Default core count for *-latest standard labels.
DEFAULT_CORES = 2


def rate_per_minute(os_name, cores=DEFAULT_CORES, self_hosted=False):
    """Return the USD/minute rate for a runner.

    os_name: one of "linux", "windows", "macos".
    cores: detected core count (2 for standard *-latest).
    self_hosted: True when the job ran on a self-hosted runner.
    """
    if self_hosted:
        return SELF_HOSTED
    os_name = (os_name or "linux").lower()
    if cores and cores > DEFAULT_CORES:
        tier = LARGER.get(os_name, {})
        if cores in tier:
            return tier[cores]
        # Unknown larger size: approximate by nearest-smaller known tier, else standard.
        smaller = [c for c in tier if c <= cores]
        if smaller:
            return tier[max(smaller)]
    return STANDARD.get(os_name, STANDARD["linux"])
