# MinuteMeter — GitHub Actions cost per job, on every PR

**See what your GitHub Actions runs actually cost.** MinuteMeter attributes a USD
cost to **each job** in a workflow run and posts the breakdown as a PR comment and
job summary — so you catch expensive jobs *before* the bill arrives.

Built for the 2026 pricing change: **self-hosted runners now cost $0.002/min**
(from 2026-03-01) and most teams have no per-job visibility into Actions **cost**,
**billing**, or **spend**. MinuteMeter runs inside your CI — no external dashboard,
no sign-up, no data leaves GitHub.

## Quick start

Add a workflow that runs after your CI completes:

```yaml
# .github/workflows/minutemeter.yml
name: MinuteMeter
on:
  workflow_run:
    workflows: ["CI"]        # the workflow you want to price
    types: [completed]

permissions:
  actions: read              # read run/job timing
  pull-requests: write       # comment the breakdown

jobs:
  cost:
    runs-on: ubuntu-latest
    steps:
      - uses: minutemeter/minutemeter@v1
        with:
          budget_usd: "1.00"   # optional: flag runs over $1.00
```

That's it. On the next run you'll get a comment like:

> ### 💸 MinuteMeter — GitHub Actions cost
> **Run total: $0.4820** (impactful jobs first) · 🔴 OVER budget $1.00? no
>
> | Job | Runner | Min | $ |
> |---|---|--:|--:|
> | integration (macos) | macos | 7 | $0.4340 |
> | build | linux | 8 | $0.0480 |
> | lint | linux | 1 | $0.0060 |

## Inputs

| Input | Default | Description |
|---|---|---|
| `github_token` | `${{ github.token }}` | Needs `actions:read` + `pull-requests:write`. |
| `budget_usd` | — | Flag the run when its cost exceeds this. |
| `run_id` | triggering run | Workflow run to analyze. |
| `pr_number` | auto | PR to comment on (auto-detected from the event). |

## How costs are computed

- Per-job duration × the runner's **list price per minute**, billed **per started
  minute** (rounded up), matching GitHub's billing model.
- Runner type is detected from job labels (`ubuntu-latest`, `windows-latest`,
  `macos-latest`, `self-hosted`, larger `*-N-cores` runners).
- Rates are GitHub's published list prices (Linux $0.006, Windows $0.010,
  macOS $0.062, self-hosted $0.002 per minute). Figures are **gross of included
  free minutes** — they show list cost, not your post-allowance invoice.

MinuteMeter never fails your CI: API or permission errors degrade to a warning.

## Free vs Pro

- **Free (this Action, MIT):** per-run, per-job cost on every PR + budget flag.
- **Pro / Team:** org-wide rollups, monthly budget tracking & alerts (Slack/Discord),
  cost history, and optimization suggestions. *(coming soon)*

## License

MIT © MinuteMeter
