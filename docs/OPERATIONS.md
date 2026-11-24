# Operations

How Grid Intelligence is refreshed, checked, deployed and protected. For the data
layers see [DATA_MODEL.md](DATA_MODEL.md); for the scoring see [SCORING.md](SCORING.md).

## Where things run

| Piece | Where |
|---|---|
| Web app + API | Vercel project `grid-intelligence`, one FastAPI function (`app.py`) serving `/api/*` and the built web app |
| Data | `data/grid.duckdb`, built by the pipeline and shipped with each deploy (never committed) |
| Bronze snapshots | GitHub releases `snapshot-ukpn-<date>` (asset `bronze-ukpn-<date>.tar.gz`), never git |
| Refresh + deploy | GitHub Actions: `.github/workflows/refresh.yml` (weekly, Mondays 05:17 UTC, and on demand) |
| CI | `.github/workflows/ci.yml` on every pull request and push to `main` |
| Git-triggered Vercel builds | **Off** (`vercel.json` → `git.deploymentEnabled: false`). The repo is linked to Vercel, but a build from git has no data (`data/` is never committed), so only the CLI / refresh workflow deploys. |

## One-time setup (repository owner)

**GitHub → Settings → Secrets and variables → Actions:**

| Name | Kind | Value |
|---|---|---|
| `UKPN_API_KEY` | Secret | UK Power Networks Open Data Portal key |
| `VERCEL_TOKEN` | Secret | Vercel access token (Account Settings → Tokens), long-lived, scoped to the team |
| `VERCEL_ORG_ID` | Variable | `team_L0zktbUdFs2mSUJTPY3vda3b` |
| `VERCEL_PROJECT_ID` | Variable | `prj_tiyW0BKIYHBywja1BxqhoAXGT11N` |

**Vercel → grid-intelligence → Settings → Environment Variables (Production):**

| Name | Value | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key | Needed for the Ask box |
| `ASK_ACCESS_CODE` | A code you share with pilot users | The Ask box stays **off** until this is set; every question must carry it |
| `ASK_RATE_PER_HOUR` | Optional, default 20 | Questions per visitor per hour (per server instance) |

**Anthropic Console → Billing → Limits:** set a monthly spend limit. It is the hard ceiling on Ask box cost; the access code and rate limit are the soft ones.

After changing Vercel variables, redeploy (Deployments → latest → ⋯ → Redeploy) or run the refresh workflow.

## The weekly refresh

`refresh.yml`, step by step:

1. Restores earlier bronze snapshots from GitHub releases.
2. Takes a new snapshot from the UKPN portal and builds everything: `uv run python -m pipeline.run --refresh`.
3. Runs the **data quality checks** (`pipeline/checks.py`, 25 checks). **A failure stops the run: nothing is stored or deployed.**
4. Stores the snapshot as a release if any dataset changed (publish date or row count); otherwise skips it.
5. Runs the full test suite and builds the web app.
6. Deploys to Vercel production.

Run it by hand: GitHub → Actions → "Refresh data and deploy" → Run workflow (untick "deploy" for a dry run).

## When a check fails

The run log lists every check with PASS / FAIL and the numbers behind it. Typical causes:

| Failing check | Likely cause | What to do |
|---|---|---|
| `rows: <dataset>` | UKPN republished with many more or fewer rows | Look at the dataset on the portal; if the change is real, rerun (the limit is ±20%) or adjust `ROW_CHANGE_LIMIT` with a note |
| `sites matched to a FLOC`, `GSP mapped`, `BSPs matched…` | Names or IDs changed at UKPN | Run `uv run python -m pipeline.profile_raw` and compare docs/PROFILE.md; update the aliases in `adapters/ukpn.py` |
| `every field has a dataset, publish date and licence` | Portal metadata missing | Check `_manifest.json` in the snapshot |
| `no dataset missing from the latest snapshot` | A download failed or a dataset was withdrawn | Rerun; if withdrawn, decide how the app copes without it |

The site keeps serving the last good deploy until a run passes.

## Deploying by hand

From a machine with the data built:

```bash
uv run python -m pipeline.run        # build + checks (must pass)
cd web && npm run build && cd ..
vercel deploy --prod                 # needs a Vercel login or VERCEL_TOKEN
```

**Rolling back:** Vercel → Deployments → pick the last good one → ⋯ → Promote to Production.

## Monitoring

- **Health:** `GET /api/health` returns the latest snapshot date, counts and whether the Ask box is enabled. Point an uptime monitor at it.
- **Ask box usage:** one JSON log line per question in the Vercel logs (`"event": "ask"`): tools used, tokens, time, a salted visitor hash. No IP addresses, no question text.
- **Error tracking** (e.g. Sentry) is not set up yet.

## Known limits

- The rate limit is per server instance (Vercel can run several), so it is a soft limit; the Anthropic spend limit is the hard one.
- First request after a quiet spell takes ~6 s (the function loads the data). Later ones take under 0.5 s.
- Snapshot history only grows when UKPN republishes; between publications the refresh stores nothing new.
