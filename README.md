# Daily DSA Solutions

This repository keeps a date-wise record of first-time accepted DSA problems tracked by the DSA Tracker application.

## Automatic daily sync

The `Daily solved-problem sync` workflow runs every day at **12:15 AM IST** and can also be started manually from the Actions tab. It:

1. Signs in to DSA Tracker using encrypted repository secrets.
2. Downloads accepted first-time submissions.
3. Creates deterministic files under `solutions/YYYY/MM/YYYY-MM-DD.md`.
4. Commits and pushes only when a newly solved problem changes the log.

### Required repository secrets

In **Settings → Secrets and variables → Actions**, add:

- `TRACKER_EMAIL` — your DSA Tracker login email.
- `TRACKER_PASSWORD` — your DSA Tracker password.

The API defaults to `https://dsa-estimators-1.onrender.com/api`. Override it with an Actions repository variable named `TRACKER_API_URL` if the deployment URL changes.

## GitHub contribution graph

Automation commits use `168968951+Tushargg1@users.noreply.github.com`, which GitHub associates with `Tushargg1`. A contribution appears only on days with at least one new solved problem and after that commit reaches the default `main` branch. GitHub can take a short time to update the graph.

## What is stored

The logs contain problem metadata—platform, title, difficulty, tags, solve time, and source link. Coding platforms do not expose private submitted source code through these public tracker APIs, so solution code must be added manually if desired.
