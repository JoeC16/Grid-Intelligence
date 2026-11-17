# Scoring

Two views of the same UKPN primary substations. Both are defined in
[`config/weights.yaml`](../config/weights.yaml) and computed by
[`pipeline/score.py`](../pipeline/score.py). The web app repeats the maths in
the browser ([`web/src/scoring.ts`](../web/src/scoring.ts)) so sliders and the
load-size input re-rank live; the two must stay in step (checked to give
identical scores and ranks for every site).

All headroom figures are **published headroom**: firm capacity from UKPN's open
data, indicative only, and not a guarantee of capacity available to connect.

## Inputs

| Column | Meaning | Source |
|---|---|---|
| `queue_mw` | Demand MW offered and not yet connected (offers made, accepted or not) | LTDS table 6; heatmap past-year offers where a site isn't in table 6 (`queue_source`) |
| `demand_headroom_mw` | Published demand headroom today; can be negative (overloaded) | LTDS capacity heatmap |
| `firm_capacity_mw`, `observed_peak_mw` | Firm capacity and 24/25 observed peak | LTDS table 3a |
| `connections_last_year` | Demand offers accepted in the past year | LTDS capacity heatmap |
| `headroom_2030_mw` | Published 2030 demand headroom, DFES Holistic Transition | DFES network headroom report |

## Investor view: stuck-demand score (default)

*Where is demand queuing beyond what the network can take?* A 0–100 score.

### Signals

| Signal | Formula | Stuck when | Weight |
|---|---|---|---|
| Stuck demand | `stuck_mw = max(queue_mw − demand_headroom_mw, 0)` | high | 25 |
| Oversubscription | `oversubscription = queue_mw / max(demand_headroom_mw, 1)` | high | 20 |
| Headroom tightness | `demand_headroom_mw` | low | 15 |
| Utilisation | `observed_peak_mw / firm_capacity_mw` | high | 15 |
| Recent activity | `connections_last_year` | high | 10 |
| Future squeeze | `headroom_2030_mw` | low | 15 |

Notes on the formulas:
- **Stuck demand is absolute MW.** It keeps a big board with hundreds of MW
  queued visible next to a small primary that's merely full.
- When headroom is **negative**, `stuck_mw` = queue + the overload. For example,
  Bow 11kV has 11.4 MW queued and −3.1 MW headroom, so 14.5 MW stuck.
- **Oversubscription is relative.** Headroom is floored at 1 MW so tiny or
  negative headroom doesn't divide by ~zero. At or below 1 MW of headroom, the
  ratio equals the queue in MW.

### Method

1. **Percentile-rank** each signal across the 959 scorable primaries, oriented
   so 1 = most stuck. Ties share the lowest rank, so every site with zero
   stuck demand gets 0 on that signal (rather than a middling value).
2. **Weighted sum** of the percentiles a site has, divided by the sum of those
   signals' weights, × 100, rounded half-up to 1 dp.
3. **Missing signals** (e.g. no firm capacity, so no utilisation): the site is
   scored on the signals it has with weights re-normalised, and the gap is
   listed in `score_missing`. Two sites are affected today.
4. Sites under an unmapped GSP (5 Willesden EPN primaries) are not scored.

Stored as `site_scores.score` and `site_scores.rank`.

### Known limitation: big boards still rank mid-table

The new signals were meant to lift big boards with a lot of stuck demand.
With the weights above they don't, yet:

| Site | Queue | Headroom | Stuck | Rank |
|---|---|---|---|---|
| Northfleet East 33kV | 399 MW | 95.2 MW | 303.8 MW | 203 |
| Rye House 33kV | 240 MW | 85.1 MW | 154.9 MW | 200 |
| Stowmarket Grid 33kV | 135 MW | 32.3 MW | 102.7 MW | 123 |

Only 2 boards at 33 kV or above make the top 50. Two reasons:

- **Percentile ranking erases magnitude.** Only 124 sites have any stuck
  demand, so 304 MW and 23 MW both sit at the 99th–100th percentile.
- **55% of the weight favours small, full sites.** Headroom tightness and
  future squeeze are raw MW (big boards have plenty). Big boards also have
  lower utilisation and little recent activity. Northfleet scores ~0 on all four.

Modelled alternatives (not applied):
- Score stuck MW on log-magnitude instead of percentile: Northfleet rises to 172nd.
- Do that, and also express headroom and 2030 headroom as a % of firm capacity:
  Northfleet rises to 87th; 7 boards at 33 kV+ make the top 50.

Getting big boards into the top 20 needs stuck MW to dominate the score, or a
separate lens. That's an open product decision.

## Developer view: connection shortlist

*Where could a load of size L connect?* Not a score: a filter and a ranking.

1. **Load size** `L`, in MW. Default 50 (`load_mw_default`).
2. **Filter:** keep sites where `demand_headroom_mw >= L`.
3. **Rank** by `headroom_after_queue_mw = demand_headroom_mw − queue_mw`,
   highest first: published headroom left after the demand already queued ahead.

Stored at the default load as `site_scores.developer_rank` (null = not
eligible). At 50 MW, 70 sites qualify; Osborn St B 11kV ranks first (137.0 MW
headroom, 4.4 MW queued, 132.6 MW left).

The filter is on headroom *before* the queue, as specified. A site can pass the
filter and still have less than `L` left after the queue, or a negative figure;
it then ranks low rather than dropping out. At 50 MW, 18 of the 70 eligible
sites have less than 50 MW left after the queue, and 4 are negative (lowest:
Northfleet East 33kV, 95.2 MW headroom − 399 MW queued = −303.8 MW). Filtering
on `headroom_after_queue_mw >= L` instead would drop these.

## Changing the scoring

Edit `config/weights.yaml`, then:

```bash
uv run python -m pipeline.score    # re-score and print the top 20 for each view
```

The web app reads the weights and views from the API, so no code change is
needed for new weights. Adding a signal needs a derived column in
`add_derived()` (if it isn't already a `sites` column) and a display entry in
`api/main.py`.
