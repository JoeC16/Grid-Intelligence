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

### One ranking per country

Percentiles and ranks are taken **within each country**, across every DNO in
it: all GB primaries together, all Spanish busbars together. A score of 90
means "more stuck than 90% of the sites in the same country". Filtering the map
to one network or distributor only hides rows; it doesn't re-rank.
(`pipeline/score.py` scores each country's rows separately; the web app shows
one country at a time, so its live re-scoring matches.)

Why not one GB + Spain ranking: the inputs mean different things. Spain
publishes firm demand *access* capacity per busbar under CNMC rules, a queue of
requests admitted but not yet evaluated, and no peak demand, forecasts or
connection counts; GB publishes headroom from the LTDS heatmap, offers made and
accepted, peak demand and DFES forecasts. Ranking them together would compare
unlike with unlike. Don't compare a Spanish score with a British one.

Within GB, several DNOs (once added) share one ranking. The DNOs publish the
same standard heatmap fields, but the queue and 2030 headroom come from each
DNO's own datasets; any signal a DNO doesn't publish is left missing (weights
re-normalised, as above) rather than filled in.

### Spain (CNMC capacity maps)

Each site is a busbar (substation × voltage) as published in the CNMC's demand
capacity map. How the signals are filled:

| Signal | Spain |
|---|---|
| Stuck demand | requests admitted and not evaluated − published headroom (firm demand access capacity available), floored at 0 |
| Oversubscription | requests waiting / max(published headroom, 1) |
| Headroom tightness | published headroom |
| Utilisation | capacity taken (ocupada) / (taken + published headroom); missing where both are 0 |
| Recent activity | not published: left out, weights re-normalised |
| Future squeeze | not published: left out, weights re-normalised |

What this means in practice:
- **86.8% of busbars have zero published headroom** (October 2026). Ties take
  the lowest percentile, so headroom tightness can't separate them: the score
  separates Spanish busbars mainly on stuck demand, oversubscription and
  utilisation. That is the honest reading of the data: most of the grid shows
  zero, and what differs is how much demand is waiting.
- Busbars the operator flags **"Nudo 0"** (408) are shown but not scored: the
  CNMC data doesn't define the flag, and every flagged busbar shows zero
  capacity, so treating it as "full" could be wrong. Two busbars with a
  published location outside Spain aren't scored either.
- The CNMC notes capacities at neighbouring nodes affect each other, so sums
  over busbars (per distributor, per area) are indicative, not additive.
- **Upstream (Phase 14)**: each busbar hangs off the Red Eléctrica transmission
  node its distributor names in the CNMC generation map ("nudo de afección").
  The node plays the BSP's role: its headroom = published demand capacity for
  ordinary loads ("no CEP") minus requests admitted at the node; queue under
  it = every linked busbar's requests waiting; effective headroom = min(busbar
  after its queue, node after the queue under it). The capacity for
  power-electronics loads (CEP, e.g. data centres; CAD1) is shown alongside.
  Node sections with the same name and voltage are merged (largest capacity,
  summed taken and admitted). Names that don't match a published node (15%)
  are shown as published with no capacity: never guessed. Small distributors
  publish no node, so their busbars are limited only locally.
- **Distributor view** (`gold.operator_mart`): one row per distribution network
  operator with busbars published, share at zero published headroom, MW
  available, MW waiting, MW stuck, MW taken and its most stuck busbar.

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

Getting big boards into the top 20 would need stuck MW to dominate the score.
Instead, the investor view has a separate "Most stuck MW" sort (below).

### Alternative sort: most stuck MW

The investor view can also rank by `stuck_mw` alone, largest first. This answers
the grid buyer's question directly ("where is the most demand stuck?") and puts
the big boards on top: Northfleet East 33kV (303.8 MW), Rye House 33kV
(154.9 MW), Stowmarket Grid 33kV (102.7 MW). Only sites with stuck demand
(`stuck_mw > 0`, 124 today) are ranked; ties share the best rank. Stored as
`site_scores.stuck_rank`.

The score is unchanged by this sort: it still means "most constrained relative
to size", which surfaces small overloaded primaries. The two together tell
both stories.

## Developer view: connection shortlist

*Where could a load of size L connect?* Not a score: a filter and a ranking.

1. **Load size** `L`, in MW. Default 50 (`load_mw_default`).
2. **Filter:** keep sites where `demand_headroom_mw >= L`.
3. **Rank** by `effective_headroom_mw`, highest first: published headroom left
   after the queue ahead, counting the bulk supply point (BSP) above the site
   (see Upstream constraints below). With "Count BSP limits" off, rank by
   `headroom_after_queue_mw = demand_headroom_mw − queue_mw` instead
   (`rank_by_local`, stored as `developer_rank_local`).

Stored at the default load as `site_scores.developer_rank` (null = not
eligible). In the web app the load size is an input; the shortlist re-ranks as
you type. At 50 MW, 70 sites qualify; Osborn St B 11kV ranks first (137.0 MW
headroom, 4.4 MW queued, 132.6 MW left).

The filter is on headroom *before* the queue, as specified. A site can pass the
filter and still have less than `L` left after the queue, or a negative figure;
it then ranks low rather than dropping out. At 50 MW, 18 of the 70 eligible
sites have less than 50 MW left after the queue, and 4 are negative (lowest:
Northfleet East 33kV, 95.2 MW headroom − 399 MW queued = −303.8 MW). Filtering
on `headroom_after_queue_mw >= L` instead would drop these. Counting BSP limits,
29 of the 70 have less than 50 MW effectively left, 6 are negative, 37 are
limited by their BSP rather than themselves, and 62 change rank.

## Upstream constraints (network graph)

Built by [`pipeline/graph.py`](../pipeline/graph.py) from the tree GSP → BSP → primary
(each primary's BSP and GSP come from the capacity heatmap; see docs/PROFILE.md
for coverage).

| Column | Meaning |
|---|---|
| `bsp_headroom_mw` | Published headroom at the BSP. Almost every BSP is also a site on the map (its own 33 kV board, for example), so this is that site's published headroom: one substation, one figure. DFES current year, default scenario, only where the BSP isn't a site. |
| `bsp_queue_mw` | Demand queued at every site under the BSP, its own board included. |
| `bsp_headroom_after_queue_mw` | `bsp_headroom_mw − bsp_queue_mw` |
| `effective_headroom_mw` | `min(site headroom after queue, BSP headroom after queue)` |
| `limiting_level` | `primary`, `bsp`, or `primary (BSP not published)` |
| `gsp_over_capacity` | The GSP's published import utilisation (peak ÷ capacity) is 100% or more. GSPs publish no MW headroom, so this is a flag, not a limit. |

Example: Kingston Grid 33kV has 116.1 MW published headroom and nothing queued
locally, but 5.8 MW is queued across the 7 sites under Kingston Grid BSP, so its
effective headroom is 110.3 MW, limited by the BSP.

The GSP overview's technical-limits RAG says whether limits have been agreed
with the system operator yet ("RED" = not yet). It is shown, but is not a
constraint signal.

### BSPs by stuck MW (investor view)

`bsps.stuck_mw = max(bsp_queue_mw − bsp_headroom_mw, 0)`: queued demand the BSP
itself can't absorb. Ranked largest first (`bsps.stuck_rank`); 28 BSPs have
some. Northfleet East is first: 422.2 MW queued under it against 95.2 MW of
published headroom, 327.0 MW stuck. BSPs with no published headroom aren't
ranked.

## Unlock planner (best next moves)

Where would added capacity at an upper-level node (a GB BSP, a Spanish
transmission node) unlock the most demand under it? `pipeline/unlock.py`,
`gold.unlock_mart` (one row per node) and `gold.unlock_curve` (node × MW added);
the web app's what-if slider repeats the same maths (`web/src/unlock.ts`;
checked equal on every node and step).

For a node with published headroom H and queue Q under it, adding A MW:

| Measure | Formula |
|---|---|
| Node headroom left | U = H + A − Q |
| Queue served (node alone) | min(A, max(Q − N − H, 0)); N = queue beyond the sites' *own* headroom, which also needs a local upgrade |
| Queue served with local work | min(A, max(Q − H, 0)) |
| New capacity | min(spare, max(U, 0)); spare = Σ max(site headroom − site queue, 0) |
| Sites open for a load L | sites with min(site after its queue, U) ≥ L (L = 10 MW by default) |
| MW to first opening | Q + L − H, if any site has L of its own headroom; otherwise it needs a local upgrade too |

- **Rankings use the gain** from adding A MW (value at A minus value at 0), so a
  node that already has room doesn't rank as a place to add more. Ties at +50 MW
  are broken by sites opened, then by the gain at +100 MW.
- Shared node capacity is never double-counted: new capacity is the lower of the
  sites' spare and what is left at the node. All queued demand counts as ahead
  of new demand.
- Two goals: **open new capacity** (room beyond today's queue) and **serve the
  queue** (customers already waiting only on the node). They differ: Northfleet
  East has 327 MW queued beyond its headroom, but 306.6 MW of it is also beyond
  its primaries' own headroom, so a BSP upgrade alone serves about 20 MW.
- Limits: a screening tool, not an engineering study. Published headroom is
  indicative and not additive, there is no power-flow model, and no
  reinforcement costs are published (the UKPN heatmap's "budget estimates" are
  quotes given to customers, in MW and counts, not £).

## Changing the scoring

Edit `config/weights.yaml`, then:

```bash
uv run python -m pipeline.score    # re-score and print the top 20 for each view
```

The web app reads the weights and views from the API, so no code change is
needed for new weights. Adding a signal needs a derived column in
`add_derived()` (if it isn't already a `sites` column) and a display entry in
`backend/main.py`.
