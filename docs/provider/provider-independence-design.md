# Provider-independent data architecture (V1.2.1 proposal)

> **Status: the provider-neutral core is IMPLEMENTED (V1.2.1 core, PR #9); provider adapters and route activations are NOT.**
> The design below is the frozen proposal; [section 19](#19-implementation-status-v121-core) records what was built, how it
> differs, and the deferrals accepted. This is part of the V1.2.1 provider-independence audit (2026-10-05). It changes
> no metric ID, signal definition, threshold or preregistered evidence. Companions:
> [`source-replacement-matrix.md`](source-replacement-matrix.md),
> [`provider-migration-priorities.md`](provider-migration-priorities.md) and
> [`v1.2.1-implementation-plan.md`](v1.2.1-implementation-plan.md). Code references are to `main` at 121874a (PR #7
> merged), and an independent review checked them.
>
> **Revision 1 (adversarial review, 2026-10-05).** The first draft had an ordered primary/fallback chain, with
> staleness-driven route selection applied after `as_of`. That design was replaced for two reasons:
> - `as_of` already collapses rows across providers, so the declared order could not hold, and windows could have holes;
> - staleness-driven switching would flip providers from week to week.
>
> The replacement is **one active route per metric, selected before `as_of`, with no automatic fallback**.
>
> **Revision 2 (final correction pass, 2026-10-06).** This revision does five things:
> - It makes route activation **point-in-time**: an append-only route history, and selection by the diagnosis time
>   (§5).
> - It limits `SourceRoute` to **routed metrics** (§3).
> - It moves access and licensing out of `equivalence_basis` into a small route-level **access policy** (§12).
> - It separates semantic equivalence from **activation validation** (§7).
> - It defines **multi-provider diagnostic anchors** (§16).
>
> The earlier "move candidate files into `observations/` on activation" step is withdrawn. Publication files are
> never moved.
>
> **Revision 3 (frozen with the Step 0 hardening change, 2026-10-06).** One wording correction, and no design change.
> §5 had said that the dictionary loader enforces the whole route-history rule set, including "append-only". A loader
> reads one current `metrics.yaml`. It can validate that file's route history (shape, order, gates, current
> consistency), but it cannot prove that the history was never edited across Git commits. §5 now separates the two,
> and says that cross-version append-only integrity must be enforced by an implementation/audit mechanism in the
> provider-neutral-core change, in addition to the existing ResearchRun retroactivity guard. That mechanism is not
> built or designed here.
>
> **Revision 4 (status only, 2026-10-06).** Records the implementation of the core. The design text is not rewritten;
> [section 19](#19-implementation-status-v121-core) lists the points where the built core is stricter than, or refines,
> what is written here.

## 0. Target shape

```text
canonical metric (metrics.yaml: id, frequency, unit, transform, tier, redistribution)          ← unchanged
      │  ROUTED metrics only (a `wind:` contract or an explicit `sources:` list):
      │    sources:        declared routes: semantic equivalence, activation validation, access policy
      │    route_history:  append-only records {effective_at, active}: which route is active from when
      ▼
provider adapter (wind.py today; pboc / csindex / chinamoney file parsers / tushare later)
      │  normalizes into the existing 12-column Observation contract (store.OBS_COLUMNS)
      ▼
provider publication file: one provider, one run, never a complete research snapshot
   data/private/observations/<provider>_<run_id>.csv   rows whose route was ACTIVE at publication time
   data/private/candidates/<provider>_<run_id>.csv     rows whose route was NOT active at publication time
   + data/private/<provider>/runs/<run_id>/manifest.json
      ▼
diagnostic anchor event: a verified ACTIVE publication with as_of T (§16)
      ▼
information set at T: public rows + every verified private publication file
      → route filter: keep each routed metric's rows of route_at(metric, T)        ← BEFORE as_of (new, small)
      → store.as_of(…, T)                                                           ← unchanged
      ▼
same deterministic signals (signals.py) and contract (private_signals.yaml)        ← unchanged
      ▼
same thesis engine; public evidence never reads private rows                       ← unchanged
```

## Terms (used with these meanings in all four documents)

| Term | Meaning |
|---|---|
| **routed metric** | A metric with a `wind:` contract or an explicit `sources:` list. Only routed metrics have routes. Every Phase 2 private signal input is routed. |
| **route** | One declared `(provider, series_key)` way of delivering a routed metric. |
| **route history** | The metric's append-only list of `{effective_at, active}` records. |
| **active at T** | The route named by the latest route-history record with `effective_at ≤ T`. Exactly one route is active at any T, by construction. |
| **candidate route** | A declared route that is not active **now** and is collected in parallel (`collect: true`). |
| **inactive route** | A declared route that is not active now and is not collected. Example: Wind on a metric that has switched. |
| **provider publication file** | One adapter run's verified output for one provider: `<provider>_<run_id>.csv` plus its manifest. It holds only that provider's rows, so it is **never** a complete research snapshot. |
| **active / candidate publication** | A publication file in `observations/` or `candidates/` respectively. Which one is decided by the route state at publication time, recorded in the manifest, and immutable. |
| **observation store** | All public observation files, plus every verified private publication file. Append-only. |
| **diagnostic anchor event** | A verified active publication that is eligible to start a diagnostic run (§16). |
| **diagnostic as_of (T)** | The anchor file's own `as_of`: the latest `retrieved_at` in it, exactly as today. |
| **information set at T** | Everything in the observation store available at T, route-filtered by `route_at(·, T)`, then `store.as_of(·, T)`. |
| **ResearchRun** | A stored private diagnostic run document, `data/private/signals/<run_id>.json` (write-once). |

**About "snapshot".** In Phase 2 code (`Snapshot`, `--snapshot`, "previous genuine snapshot"), "snapshot" means one
Wind file, and a Wind run happened to be a full private refresh. That equivalence ends with independent providers.
These documents therefore say *publication file* for a provider's output, and *anchor* for what starts a run. The
phrase "local Wind snapshot" in evidence text still refers to the Wind publication file
`wind_20261004T195141Z.csv`.

## Current Wind dependency map

Sections 1–15 answer the fifteen design questions in order. This map comes first because every answer refers to it.

| # | Location | Coupling | Severity |
|---|---|---|---|
| C1 | `src/cnmacro/signals.py:186-187` | The signal-contract loader rejects any input metric with `m.wind is None` ("not a private Wind metric"). This is the **only** place the signal engine needs a `WindContract`. The arithmetic itself uses only `metric_id`, `reference_period`, `value`, `retrieved_at` and `_file`. | **Blocking.** No non-Wind metric can feed A1–X1. |
| C2 | `src/cnmacro/diagnose.py:31-32, 59-82, 172` | Snapshot discovery globs `wind_*.csv`, requires `data/private/wind/runs/<id>/manifest.json`, and resolves `--snapshot` as `wind_{id}.csv`. With no Wind file, no diagnosis runs. | **Blocking** |
| C3 | `src/cnmacro/store.py:35-62, 84, 91-113` | `Metric.wind: WindContract \| None` is the only route slot, and the `WIND_*` vocabularies sit in the generic store. `source_primary` and `source_fallback` are single free-text strings, and nothing reads `source_fallback`. | Structural |
| C4 | `src/cnmacro/wind.py:486-531, 223-234, 541-565` | Month-end aggregation (`cn_cgb10y`) and the two-view fan-out (`same_series_as`) exist only inside the Wind adapter. | Structural |
| C5 | `store.as_of` (`store.py:185-186`); `signals._Ctx.points` (`signals.py:226`) | Both keep one row per (metric, period), the one with the latest `retrieved_at`, **whatever the source**. A second provider would silently interleave with the first. | **Semantic hazard** |
| C6 | `src/cnmacro/ingest.py:25, 343` | `source_class` is inferred from the provider **name** (`PUBLIC_SOURCES`). | Boundary leak by name |
| C7 | `src/cnmacro/cli.py:259-303, 297`; `wind_runtime.yaml:41-47` | `refresh-private` means a Wind refresh. The summary reads the Wind-specific `manifest["skill"]`. The history depths the signals need (130, 500 and 75 days) live in Wind's runtime file. | Operational |
| C8 | `store.load_observations` as used by `diagnose.py:182` | It loads **every** CSV in `data/private/observations/`, not only manifest-verified files. Verification picks only the anchor file. | Integrity gap |
| C9 | Tests: `test_signals.py:76`; `test_wind_dictionary.py:33-49`; `signal_support.py` (`wind_SYNTHETIC1`, the Wind run layout); `test_diagnose.py` (`wind_*.csv`) | They pin C1–C2. | — |
| C10 | Text: `diagnose.py:289, 298, 381` (report wording), `signals.py:215` (docstring), CLI help, `docs/data-policy.md` rules 2/3/6, `v1.2-phase2-binding.md:11` | Wording only. Rule 6 is already enforced generically through `source_class`. | Wording |
| C11 | `metrics.yaml` `cn_cgb10y.source_fallback: ChinaBond (CCDC) published curve` | It names a **different curve builder** as a fallback for the ChinaMoney series. | **Latent semantic hazard** (§14) |
| C12 | `diagnose.py:37, 185-188` | `RUN_FIELDS` and the run identity know nothing of routes. The anchor's `as_of` is the only time input, and nothing records which provider was authoritative at that time. | **Blocks point-in-time routing** (§5, §11) |

These parts are **already provider-neutral** and stay unchanged:
- `store.available_at` and `store.as_of`, keyed on `source_class`, `release_date` and `retrieved_at`;
- `checks.py` and `refresh.route`, keyed on `tier` and `redistribution`;
- the signal definition hashes, which contain metric IDs only (`signals.py:79-84`);
- `information_set_sha256`, which covers file stems;
- the site build, which reads `data/demo` only;
- `check_secrets.py`, which blocks `data/private/**`.

`cn_cgb10y` is in no evidence test or terminal rule (`test_wind_dictionary.py:73`), and `public_state` reads public
rows only. A change of its provider therefore cannot alter preregistered evidence. It affects only the private
`check`, where a core metric with no rows is a FAIL (`checks.py:82`).

**Consequence.** A provider swap under an unchanged `metric_id` leaves every `definition_sha256` unchanged. That is
correct only for semantically EXACT substitutes. The job of this design is to make a swap **explicit, reviewed,
time-stamped, recorded and non-splicing**.

## 1. What stays canonical and provider-independent

These keep one owner and do not change:
- in `metrics.yaml`: `metric_id`, `name`, `frequency`, `unit`, `transform`, `tier`, `hypotheses`, `role`,
  `caliber_notes` and `redistribution`;
- the signal contract (`private_signals.yaml`);
- the Observation contract;
- the as-of semantics;
- publication-file immutability;
- write-once ResearchRuns.

A provider never defines what a metric means. It declares only how it delivers that meaning, with what proven
fidelity, under what access terms, and from when.

## 2. Where provider metadata lives

`sources:` and `route_history:` sit in **`metrics.yaml`**, next to the canonical definition of each routed metric.
This extends Phase 1's rule that the dictionary is "the one place a Wind route is pinned". These blocks hold no data
values and no credentials, so they are safe in a tracked file.

Operational constants (spacing, budgets, windows) stay in each adapter's runtime file, as `wind_runtime.yaml` does
today. A new adapter gets a runtime file only if it needs one. Credentials never appear in any tracked file.

## 3. Should `Metric` contain provider contracts directly?

No. A **routed** `Metric` holds provider-neutral route records, plus its route history. Each route carries an opaque
payload that only its adapter validates.

```python
@dataclass
class AccessPolicy:                     # route-level; NOT evidence of equivalence (§12)
    automated_retrieval: str            # permitted | unknown | prohibited   (network fetch by an adapter)
    manual_import: str                  # permitted | unknown | prohibited   (a human-saved producer file, parsed locally)
    private_use: str                    # permitted | unknown | prohibited   (storing and using the values privately)
    redistribution: str                 # permitted | unknown | prohibited   (only ever relevant to a public metric)
    basis: str                          # terms page + date read, or the recorded human decision; no free-form legal advice

@dataclass
class SourceRoute:                      # store.py (provider-neutral)
    provider: str                       # adapter key, [a-z0-9-] only ("_" separates provider and run_id in filenames)
    series_key: str                     # stable provider-native identifier (EDB code, ts_code, "SDDS_10Y"); never a URL
    equivalence: str                    # SEMANTIC ONLY: EXACT | FUNCTIONALLY_EQUIVALENT | APPROXIMATE | NOT_EQUIVALENT | UNKNOWN
    equivalence_basis: str = ""         # SEMANTIC evidence only: method identity, identity transformation, overlap n/n, max |Δ|
    validation: str = "PENDING"         # activation validation: PENDING | PASSED | FAILED
    validation_basis: str = ""          # the full candidate-period comparison: periods, n/n, private evidence path (no values)
    access: AccessPolicy = ...          # required; there is no default permission
    collect: bool = False               # collect this route in parallel while it is NOT active (a candidate route)
    aggregate: str | None = None        # month_end: this view is the last observation of each completed month
    same_series_as: str | None = None   # one fetch feeds two views (cn_cgb10y_daily → cn_cgb10y)
    expected: dict = field(default_factory=dict)      # {name, freq, unit}; drift fails closed
    known_gaps: list[dict] = field(default_factory=list)
    params: dict = field(default_factory=dict)        # adapter-specific; never read by the core

@dataclass
class RouteChange:                      # one immutable route-history record
    effective_at: str                   # "genesis", or a UTC ISO timestamp
    active: str                         # provider key of a declared route
    decision: str = ""                  # reference to the reviewed change (and to the human decision it rests on)
```

A route has **no stored `status` field.** Status is derived:
- `active` at T is defined by the route history (§5);
- **now**, a non-active route is `candidate` if `collect: true`, otherwise `inactive`.

Only "active at T" is ever evaluated historically.

```yaml
# illustrative only; not a proposal to activate anything
cn_dr007:
  wind: { code: M1006337, ... }                      # unchanged; becomes the params of the wind route
  sources:
    - provider: wind
      series_key: M1006337
      equivalence: EXACT
      equivalence_basis: "incumbent: the canonical definition was pinned on this route (Phase 1)"
      validation: PASSED
      validation_basis: "incumbent"
      access: { automated_retrieval: permitted, manual_import: prohibited, private_use: permitted,
                redistribution: prohibited, basis: "user's Wind subscription; docs/wind-capability-note.md §10" }
    - provider: chinamoney-dr
      series_key: DR007
      equivalence: EXACT
      equivalence_basis: "same CFETS DR007 weighted rate; 47/47 equal at 4 dp, 2026-07-27..09-29, same missing day"
      validation: PENDING
      access: { automated_retrieval: prohibited, manual_import: unknown, private_use: unknown,
                redistribution: prohibited, basis: "CFETS 法律声明 read 2026-10-05; no written permission" }
  route_history:
    - { effective_at: genesis, active: wind }
```

**Scope: which metrics are routed.**
- `SourceRoute` routing applies **only** to metrics that already have a `wind:` contract or that explicitly define
  `sources:`.
- The compatibility shim synthesizes a Wind route **only when `metric.wind is not None`**.
- Existing public metrics without `sources:` stay exactly as they are. That covers the NBS, PBOC, MOF, GACC, FRED and
  SAFE metrics fetched by `scripts/fetch_*.py` and ingested by `refresh-public`. They are not routed: they have no
  route, no route history, no route filter and no new loader rule.
- The exactly-one-active-route invariant, the activation gates (§7) and the route filter (§6) apply **only to routed
  metrics**.
- **Phase 2 private signal inputs must be routed.** Their routes must satisfy the active EXACT/FE rule at every T
  (`signals.py:186-187`, C1).

**Wind compatibility shim (V1.2.1).** The existing `wind:` block stays as it is and becomes the `params` of the Wind
route.
- **A metric with `wind:` and without `sources:`.** It gets one synthesized route: `{provider: wind, series_key:
  <wind.code>, equivalence: EXACT, validation: PASSED, basis "incumbent", access per the Wind subscription}`. It also
  gets the synthesized history `[{effective_at: genesis, active: wind}]`. That is today's behaviour, and `wind.py` and
  its tests are unchanged.
- **A metric with `wind:` and `sources:`.** It must list Wind explicitly, and its route history must begin with
  `{effective_at: genesis, active: wind}`. That Wind entry draws its params from the `wind:` block.
- **A metric without `wind:`.** It gets no synthesized route. If it declares `sources:`, it must also declare a
  `route_history` whose first record is `genesis`.
- **Unchanged.** Wind's descriptive fields (`role`, `evidence_use`, `priority`, `mirrors`) stay Wind metadata. They are
  not route state, and nothing in the core reads them.
- **Moved.** `WindContract` and the `WIND_*` enums move from `store.py` to `wind.py`.

## 4. ProviderContract, SourceRoute, MetricSource?

**Only `SourceRoute`**, with its two small value records, `AccessPolicy` and `RouteChange`. There is no
`ProviderContract` hierarchy, no registry and no plug-in loader.

The adapter "interface" is a convention: a module with `run(...) -> RunOutcome` that publishes through a shared
function, `publish(staged_rows, provider, run_id, at)`. That function is `wind.publish_snapshot`
(`wind.py:661-678`) generalized in one way: it splits rows by route state at publication time. Rows of routes active
at `at` go to `observations/`; all other rows go to `candidates/`. Both are written atomically and append-only.

The shared row builder, `validate_rows` and the drift checks move to a small `normalize.py`. The month-end rule moves
there too, driven by the route's `aggregate: month_end` exactly as it is driven by `wind.aggregate` today. That
replaces the first draft's general `DeriveRule`: one rule, one place, for any provider.

- **Coverage guard for month-end (new).** Wind always returned data through the retrieval date. A file or partial
  response can end earlier. So the latest daily date in the batch must fall in a **later** month than every month
  emitted. Otherwise a truncated download would store an earlier day as the month-end of the core metric.

**Run manifest.** It keeps the existing schema: `status`, per-call `params` and `raw_sha256`, `retrieved_at`,
`started_at` and `completed_at`. It changes in four ways:
- `publication` names up to two files, `observations` and `candidates`, each with `{file, rows, sha256}`;
- `route_states` records, per metric in the run, the route active at publication time;
- the Wind-specific `skill` block generalizes to `runtime: {kind, version, fingerprints}`, and `cli.py:297` reads
  that instead;
- existing Wind manifests are read as they are: their single file is an active publication under the genesis record.

## 5. How multiple providers for one metric work: temporal routing

A routed metric may declare several routes. **Which one is authoritative is a function of time**, given by its
append-only route history.

```text
route_at(metric, T) = the `active` of the last record in metric.route_history with effective_at ≤ T
                      ("genesis" sorts before every timestamp)
```

**Route-history rules.** Each rule is enforced in a different place, because one current `metrics.yaml` can show
some things and not others.
1. **Append-only.** Records are never edited, removed or reordered. *Enforced across versions, not by the loader:
   see "What a loader can and cannot prove" below.*
2. **Ordered.** The first record is `genesis`. Later `effective_at` values are strictly increasing UTC timestamps.
   *Load time, on the current file.*
3. **One active route.** Exactly one route is active at any T, because exactly one record applies. This is the
   "exactly one active route" invariant in temporal form: an `active_from` / `active_until` interval set with no
   overlaps and no gaps. *Load time: it holds by construction once rule 2 holds.*
4. **Gated.** Every record names a declared route that passes the activation gates (§7). *Load time, on the current
   file.*
5. **Activation is an appended record.** Activating a route appends `{effective_at: E, active: <provider>, decision:
   <ref>}`. *Reviewed change; rules 1 and 6 are what check it afterwards.*
   - E is the wall-clock time of the reviewed change. It is never back-dated.
   - The previous route stops being active at E. No other record changes.
   - Re-activating Wind later is just another appended record.
6. **Retroactivity guard.** This is enforced by `diagnose`, which can see the stored runs. For every stored
   ResearchRun, `route_at(m, run.as_of)` must equal the `routes[m]` recorded in that run, for every routed input `m`.
   A stored run without a `routes` field predates V1.2.1, so it must equal the genesis state (all Wind). On any
   mismatch, `diagnose` fails with `ROUTE_HISTORY_RETROACTIVE` and writes nothing. Provider switching therefore cannot
   rewrite the meaning of a ResearchRun that already exists.

**What a loader can and cannot prove.**
- The dictionary loader sees one version of `metrics.yaml`. It can validate that version's route history: its shape,
  the genesis-first order, strictly increasing timestamps, that each record names a declared route, that the gates
  hold, and that exactly one route is active at every T (rules 2–4).
- It **cannot** prove that the history was never edited, removed or reordered between Git commits (rule 1). On its
  own, a rewritten history is as well-formed as an honest one.
- The retroactivity guard (rule 6) does not close that gap. It protects only what a stored ResearchRun recorded. An
  edit that contradicts no stored run passes it. Examples: a change confined to records that take effect after the
  latest stored run's `as_of`, or a changed `decision` reference.
- **Cross-version append-only integrity is therefore a separate requirement.** It must be enforced by an
  implementation/audit mechanism in the provider-neutral-core change (§18), in addition to the retroactivity guard.
  Choosing that mechanism is part of that change. It is not designed or implemented by the Step 0 hardening change,
  which adds no code for it.

**Collection.**
- The route active **now** is collected, and its rows are published to `observations/`.
- A candidate route (`collect: true`, not active) is collected in parallel, and its rows are published to
  `candidates/`.
- An inactive route is not collected. An explicitly requested run (`--provider wind`) still splits its rows by route
  state.

**Candidate isolation.**
- Candidate publications are **never moved**, never renamed and **never anchors** (§16).
- Their rows are excluded from every information set at T unless their route is active at T.
- Once their route is active, they may serve as *history* for runs at T ≥ E. Their `retrieved_at` is genuine, because
  we did hold those values at that time. Candidate rows never enter a run with T < E.

**No back-dated publication after activation.**
- A publication made at or after its route's `effective_at` must have every row's `retrieved_at` inside that run's
  own `[started_at, completed_at]` window. Otherwise it fails with `ROUTE_BACKFILL_AFTER_ACTIVATION`.
- Re-deriving rows from retained raw responses keeps the original `retrieved_at`. Example: the property use filter is
  settled after collection has started. Such a re-derivation is allowed **only while the route has never been
  active**, that is, into `candidates/` before E.
- After activation, a changed definition is a new `series_key`, which needs its own activation record.

**Worked sequence** (the test in §15):

| Time | Event | `route_at(cn_dr007, ·)` | What a run at this time sees |
|---|---|---|---|
| T1 | `chinamoney-dr` candidate publication, rows retrieved at T1, written to `candidates/` | wind | — (not an anchor) |
| T2 | Wind active publication (anchor); ResearchRun R2 stored with `routes.cn_dr007 = wind` | wind | Wind rows only. The T1 candidate rows are filtered out. |
| T3 | Reviewed change appends `{effective_at: T3, active: chinamoney-dr}` | chinamoney-dr from T3 | — |
| T2 replay | `diagnose-private --anchor wind_<T2 run>` | wind (evaluated at T2) | Identical to R2. Write-once reports `reproduced`. |
| T4 | `chinamoney-dr` active publication (anchor) | chinamoney-dr | `chinamoney-dr` rows from T1 and T4. No Wind row enters `cn_dr007`'s window. |

## 6. Priority: primary, fallback, cross-check

- **There is no automatic fallback.** The previous primary becomes the fallback only through a reviewed, appended
  route-history record. This was chosen deliberately over a priority chain:
  - a chain built on `as_of` cannot keep its declared order;
  - staleness-driven switching would change providers from week to week;
  - a late manual import should produce INSUFFICIENT_DATA with a visible staleness message, not a silent switch.
- **The route filter runs before `as_of`.** It is one function, `select_active(obs, metrics, at)`. For every
  **routed** metric, it drops rows whose `(source, source_code)` is not `route_at(metric, at)`'s `(provider,
  series_key)`. Non-routed (public) metrics pass through untouched. It is applied wherever private observations are
  combined, always with that path's own evaluation time:
  - in `diagnose`, at the anchor's T, before `as_of`;
  - in the private `check` and `evaluate` paths, so the core `cn_cgb10y` cannot interleave there either.

  Because filtering happens before the per-period deduplication, `as_of` sees one provider per routed metric. Every
  window is single-source, and cross-provider collapse cannot create holes.
- **Cross-check.** An APPROXIMATE route can only ever be a candidate. The loader refuses to name it in a route-history
  record. A comparison report reads `candidates/` against `observations/`.

## 7. Semantic equivalence and activation gates

**Semantic equivalence** answers one question: *is this the same statistic?* It is a fixed property of the route:

| equivalence | may be named in `route_history` for an existing `metric_id` | otherwise |
|---|---|---|
| EXACT | yes, if the other gates pass | — |
| FUNCTIONALLY_EQUIVALENT | yes, with a stated identity transformation (e.g. "ROUND_HALF_UP to 2 dp"), if the other gates pass | — |
| APPROXIMATE | **no** | candidate only (cross-check), or a **new metric_id** with a **new signal version** to consume it |
| NOT_EQUIVALENT | **no** | not attached; a new metric if wanted |
| UNKNOWN | **no** | candidate until resolved |

**Activation readiness is separate.** A route may be semantically EXACT and still not ready to activate. A route can
be named in a route-history record only when **all** of these gates hold:

| Gate | Requirement | Checked |
|---|---|---|
| G1 semantic | `equivalence` is EXACT, or FE with its identity transformation stated; `equivalence_basis` cites the semantic evidence | at load, for every route the history names |
| G2 validation | `validation: PASSED`, with a `validation_basis` recording a candidate-period comparison against the incumbent, **compared individually per period** over every incumbent period available locally | at load, for every route the history names |
| G3 access | `access.private_use: permitted`; and the adapter's retrieval mode is permitted: `automated_retrieval: permitted` for a fetching adapter, or `manual_import: permitted` for a file parser. `unknown` fails closed. | at load, for the route active **now** (access is a present-tense permission; past records stand) |
| G4 temporal | `effective_at` is the time of the change; the retroactivity guard holds (§5, rule 6) | in `diagnose` |
| G5 boundary | the metric stays `private_only` unless separately approved; a `public` metric needs `access.redistribution: permitted` on its active route | at load |

Every route, the EXACT ones included, enters as a candidate and is validated before activation. When the incumbent is
Wind and credits are gone, the comparison runs against Wind's last private publication file on disk.

If a gate later fails for the route active now, the remedy is a new appended record. Example: terms change to
prohibit automated retrieval, so the metric switches back to Wind. Records are never edited. Until the switch is made,
the loader refuses to run that adapter.

## 8. How units, frequency and metadata are validated

These are the Phase 1 rules (`wind.validate_contracts`, `metadata_differences`, `validate_rows`), generalized.

- **Load time.**
  - `expected.freq` must equal `metric.frequency`, unless the route has `aggregate: month_end` (then D → M).
  - A unit that differs from the canonical unit needs an explicit scale (万亿 → 亿 ×10000).
  - Missing metadata must be a declared `known_gap`.
  - One `series_key` maps to one concept per provider, except an explicit `same_series_as` pair.
- **Run time.**
  - A returned name, frequency or unit that differs from `expected` → `METADATA_DRIFT`.
  - A missing or renamed field, column or label, or an HTML/WAF page where data was expected → `SCHEMA_DRIFT`.
    Column positions in header-less files are checked against a recorded shape *and* against a known value pattern,
    because a positional check alone cannot catch a reorder.
  - A value outside the route's plausibility band → `IMPLAUSIBLE_VALUE`.
  - All three fail closed.
  - Label maps normalize full-width and half-width punctuation (企（事）业单位 = 企(事)业单位) before matching.
- **Before publication.** `validate_rows` checks:
  - `source == provider` and `source_code == series_key`;
  - the `source_class` derived from the metric;
  - the run-window rule for active publications (§5).

  It no longer checks Wind literals.

## 9. How provider-specific failures are represented

Every adapter's failure type uses one shared code vocabulary:
- Access and limits: `AUTH_ERROR`, `ACCESS_NOT_PERMITTED`, `BLOCKED_QUOTA`, `BLOCKED_PERMISSION`, `RATE_LIMITED`.
- Transport and results: `NETWORK_ERROR`, `NO_RESULTS`, `INCOMPLETE_RESULT`, `MALFORMED_RESULT`.
- Drift and values: `METADATA_DRIFT`, `SCHEMA_DRIFT`, `RUNTIME_DRIFT`, `IMPLAUSIBLE_VALUE`.
- Run control: `CALL_BUDGET_EXCEEDED`, `LOCAL_ONLY`.
- Route history: `ROUTE_BACKFILL_AFTER_ACTIVATION`, `ROUTE_HISTORY_RETROACTIVE`.

`ACCESS_NOT_PERMITTED` is raised **before** any network call, when an adapter is asked to fetch a route whose
`automated_retrieval` is not `permitted`. It is also raised when a file is offered to a parser whose `manual_import` is
not `permitted`. Wind's codes map one-to-one (`WIND_METADATA_DRIFT` → `METADATA_DRIFT`, with `provider: wind`). The CLI
envelope keeps its shape and gains `provider`.

A failed run publishes nothing for that provider and leaves other providers untouched. The diagnosis report adds a
**route table**. For each routed input metric, it gives:
- the route active at T, and the `effective_at` of that route's record;
- the route's newest `retrieved_at` at or before T;
- the last run status of that provider.

Staleness is still reported by the signal itself, with the same "latest observation is N days old" message as
today.

## 10. How availability and as-of semantics differ by source

They differ only through `source_class`, which comes from the metric. `store.available_at` is unchanged.

- **Private rows: `available_at = retrieved_at`, always.** This holds for every provider. A free official producer does
  not make a private metric's rows public.
- **What `retrieved_at` means for a manual file.** It is the **import time**: the moment our system first holds the
  data. It is never the download time the researcher claims, which is unverifiable and could back-date rows into
  information sets that have already been diagnosed. The claimed download time and the file's SHA256 go into the run
  manifest only. This matches how the existing inbox stamps rows (`now_iso`).
- **Capture-only sources** (municipal pages, which publish only the latest day) accumulate their own history. Nothing before the first capture is filled
  from any other provider, because the route filter forbids it.
- **Route state and availability are independent.**
  - `available_at` decides *whether a row was known at T*.
  - `route_at` decides *whether its route was authoritative at T*.

  A row enters the information set only if both hold.

## 11. How exact provenance is preserved

- **Per row.** `source` is the provider and `source_code` the series_key. The row also carries `source_class`,
  `retrieved_at` and `limitation`. `limitation` holds the method note, for example "single month = reported YTD(m) −
  YTD(m−1)", or "month-end: last observation dated 2026-09-30".
- **Per publication.** The manifest records:
  - the request params, or the input file's name and SHA256 for a manual import;
  - the raw SHA256, the runtime block and each published file's SHA256;
  - `route_states` at publication time.
- **Per ResearchRun.**
  - The run gains `anchor` (§16) and `routes`. `routes` maps each routed input to `{provider, series_key,
    equivalence, effective_at}`, evaluated at T.
  - `routes` is added to `RUN_FIELDS`, the fields a rerun must reproduce. A stored run without `routes` predates V1.2.1
    and is compared as the genesis state (all Wind), so existing runs replay as `reproduced`.
  - **The run-ID construction is unchanged.** `information_set_sha256` already fixes which rows were used, including
    their file stems, and the stem begins with the provider. Existing Wind run IDs (`<run_id>-<hash>`) therefore keep
    their form. A non-Wind anchor's run ID is `<provider>_<run_id>-<hash>`.
  - `compare` annotates every signal whose input route differs between the previous and current anchors, so a provider
    switch is never read as an economic change.
- **Loading.** The private loader reads only **manifest-verified** publication files, from `observations/` and
  `candidates/` (fixes C8). The route filter then decides which rows count at T. Pre-existing private inbox CSVs are
  not Phase 2 inputs, and only the commands that already used them load them.

## 12. How access and redistribution attach to the route and the observation, not to Wind

**Semantic evidence and access policy are kept apart.**
- `equivalence` and `equivalence_basis` record only whether the route delivers the same statistic.
- `access` records what we may do with the route.

Neither field may hold the other's content.

`access` has four status fields plus a `basis`:

| Field | Values | Governs |
|---|---|---|
| `automated_retrieval` | permitted / unknown / prohibited | whether an adapter may fetch over the network |
| `manual_import` | permitted / unknown / prohibited | whether a human-saved producer file may be parsed and stored |
| `private_use` | permitted / unknown / prohibited | whether the values may be stored and used privately at all |
| `redistribution` | permitted / unknown / prohibited | whether the metric could ever be reclassified public (G5) |

- **Manual-file-import-only routes.** These have `automated_retrieval` other than `permitted` and `manual_import:
  permitted`. Their adapter is a file parser that never touches the network.
- **Fail closed.** `unknown` is treated as `prohibited` for every gate.
- **Use conditions.** A conditional permission, such as "non-commercial use only", stays `unknown` until a human
  records that the condition is met. `basis` then cites that recorded decision.
- **No implied permissions.** A paid key, a free endpoint, or a key's secrecy grants none of these permissions.
- **`source_class` is unchanged.** It is still derived from `metric.redistribution` and written into every row, and
  `validate_rows` checks it. The inbox path stops inferring it from provider names (C6). All V1.2.1 routed metrics stay
  `private_only` unless a separate written decision under data-policy rule 2 approves otherwise.
- **CFETS / ChinaMoney routes fail closed.**
  - They are `automated_retrieval: prohibited` without written permission, because the 法律声明 forbids "电子抓取"
    without consent.
  - They are `manual_import: unknown` and `private_use: unknown`, because the legal footing of manual private copying
    is unresolved.
  - The parser may be written and tested on **synthetic fixtures**. No producer file is fetched, imported or activated
    until a recorded decision changes these fields.
- **Policy wording.** Data-policy rules 2, 3 and 6 are reworded from "Wind-derived" to "licensed or
  private-route-derived". Their substance does not change.

This is not a licensing platform. There are four fields and a citation, the loader reads them in two gates (G3, G5),
and adapters check them in one place (`ACCESS_NOT_PERMITTED`).

## 13. How refresh orchestration works

- **`refresh-private [--provider P ...]`** runs the selected adapters in sequence. Each adapter does its own runtime
  check, budget, atomic publication and manifest.
  - Without `--provider`, it runs the adapters of the routes that are active now, plus candidate routes that cost
    nothing per call. An adapter runs only if its retrieval mode is permitted.
  - **Wind runs only when named** (`--provider wind`).
- **File-parser providers** read the producer's own file from `data/private/inbox/<provider>/`, only for routes with
  `manual_import: permitted`. They publish a normal publication file whose `retrieved_at` is the import time.
  - A file whose SHA256 has already been imported is refused, so re-runs never duplicate rows.
  - If written permission later allows automation, only the fetch step is added. The parser, route and metric stay.
- **History windows** for each active route are checked by a test against the needs derived from
  `private_signals.yaml`. They are no longer hand-copied into an adapter file (C7).
- **`diagnose-private`** discovers diagnostic anchor events of any provider (§16). The Phase 2 `wind_*.csv` discovery
  is generalized to `observations/<provider>_<run_id>.csv` with the byte-matching
  `data/private/<provider>/runs/<run_id>/manifest.json`, split on the first underscore.
- **Daily collection sources** need a local Windows Task Scheduler entry. They never run in GitHub Actions
  (`cli.py:266`).

## 14. How silent fallback is prevented from changing the economic concept

1. Only EXACT, or FE with a stated identity transformation, can be named as active for an existing ID. Each must also
   pass activation validation and the access gates (§7).
2. At any T, exactly one route is active, given by an append-only route history. Nothing switches automatically
   (§5, §6).
3. Selection by `route_at(·, T)` happens before `as_of`, so no window splices two providers (§6).
4. Every activation is a reviewed, time-stamped record.
   - It is never back-dated, and it can never change what a stored run used (§5, rule 6).
   - It is recorded in each run's `routes` and annotated in comparisons (§11).
5. **Retire C11.** Remove `cn_cgb10y.source_fallback: ChinaBond (CCDC) published curve`. A CCDC 10Y would be a new
   metric (e.g. `cn_cgb10y_ccdc`), never a route for `cn_cgb10y` or `cn_cgb10y_daily`.
6. Prefer the producer that Wind itself republishes: ChinaMoney for DR007 and the 10Y, PBOC for loans, CSI for the
   index.

## 15. Tests that would show substitution does not change signal meaning

| Test | What it proves |
|---|---|
| **Golden provider swap.** Identical observations are written as `wind_X.csv` and as `<provider>_X.csv`. Both give identical `status`, `numeric_components` and `definition_sha256`, and differ only in input-ID stems. | The engine is provider-blind for EXACT data. |
| **Late-retrieved inactive provider.** An inactive or candidate provider's rows are retrieved *after* the active provider's rows for the same periods. Signals use only the active route's rows, every window is single-source, and there are no holes. | Fixes C5 and review blocker B1. |
| **Temporal activation sequence.** <br>1. A candidate is published at T1. <br>2. A Wind anchor at T2 stores run R2. <br>3. A record activating the candidate at T3 is appended. <br>4. Replaying T2 reproduces R2 byte-for-byte in `RUN_FIELDS` (status `reproduced`), with `routes.cn_dr007 = wind` and no candidate row in the frame. <br>5. A new anchor at T4 selects the new provider, includes its T1 rows as history, and includes no Wind row for that metric. | Point-in-time routing; activation never rewrites a stored run. |
| **Pre-activation candidate is never an anchor.** The T1 candidate file is not an anchor before T3, after T3, or if copied into `observations/` (its route was not active at its own T1). `--anchor` naming it fails with `ANCHOR_NOT_ELIGIBLE`. | §16 |
| **Retroactive record refused.** A record with `effective_at` before a stored run's `as_of` makes `diagnose` fail with `ROUTE_HISTORY_RETROACTIVE` and write nothing. | §5, rule 6 |
| **No back-dating after activation.** An active-route publication with a row retrieved before its run window fails with `ROUTE_BACKFILL_AFTER_ACTIVATION`. A pre-activation re-derivation into `candidates/` is accepted. | §5 |
| **Legacy runs replay.** A stored Phase 2 run with no `routes` field replays as `reproduced` under the synthesized genesis history. | §11 |
| **Route-history load rules.** These all fail to load: a history not starting at `genesis`; non-increasing timestamps; a record naming an undeclared route; a record naming an APPROXIMATE, UNKNOWN, `validation: PENDING` or `FAILED` route; an EXACT/FE route without `equivalence_basis`. These are all single-file checks. | §5, §7 |
| **Append-only across versions.** Editing, removing or reordering a record that an earlier accepted version of the history contained is rejected, **including when no stored run is affected**. An unchanged history, and one with a new record appended, are accepted. The mechanism is chosen in the core change. | §5, rule 1 |
| **Routing scope.** A public metric without `wind:` or `sources:` gets no synthesized route, and its rows pass the route filter untouched. The existing public `check`, `evaluate` and `refresh-public` outputs are byte-identical before and after. A Phase 2 signal input that is not routed fails the signal-contract load. | §3 |
| **Access fails closed.** A fetching adapter on `automated_retrieval: unknown` or `prohibited` raises `ACCESS_NOT_PERMITTED` before any network call. A parser on `manual_import: unknown` refuses the file. A route with `private_use` other than `permitted` cannot be the active route now. | §7 G3, §12 |
| **Candidate isolation.** Rows in `candidates/` never appear in the `diagnose`, `check` or `evaluate` frames at any T before their route's `effective_at`. Candidate files are never moved. | §5 |
| **Manual import.** `retrieved_at` equals the import time, not the claimed download time. Re-importing the same SHA256 is refused. A truncated file does not emit an incomplete month-end. | §10, and the month-end coverage guard (§4) |
| **Unverified files excluded.** A CSV in `observations/` or `candidates/` without a matching manifest is not loaded by `diagnose`. | C8 |
| **As-of unchanged.** `test_private_asof.py`, re-run with a non-Wind `source`, passes. | §10 |
| **Month-end parity.** The shared month-end rule on Wind fixtures equals the current `wind.py:508-524` output on (period, numeric value, month-end date). The `limitation` text and the value repr are expected to differ, so they are not compared. | §4 |
| **Route change annotated.** `compare` between an anchor before E and one after E annotates every affected signal with "input route changed". | §11 |
| **Windows cover the contract.** Each active route's request or file horizon is at least what the signal contract needs. | C7 |
| **Wind still works.** The existing Wind tests pass, except the C9 assertions. Those are reworded from "has a Wind contract" to "is routed, and every route its history names is EXACT/FE and PASSED". | — |
| **Parser fixtures.** Synthetic look-alikes of each source parse to the expected rows. A mutated header, a reordered column, an HTML/WAF page, or a full-width/half-width label variant gives the documented outcome. | §8 |

## 16. Diagnostic anchors and information sets (multi-provider)

**Why this changes.** Under Wind, one Wind file was both a provider publication and a full private refresh, so
"diagnose the newest snapshot" was well defined. With independent providers refreshing at different times, no single
provider file is a complete research snapshot. A run must therefore be defined by a **time**, and by the **complete
information set** at that time.

**What creates a diagnostic run (event-driven).**

```text
verified ACTIVE provider publication at time T                     (the diagnostic anchor event)
  → assemble the complete eligible information set as of T:
       public observations                     (unchanged)
     + every manifest-verified private publication file, any provider, observations/ and candidates/
     → select_active(·, metrics, at=T)         route state effective at T, for routed metrics only
     → store.as_of(·, T)                       private rows only from their own retrieved_at ≤ T
  → run the deterministic signals and the public state at T
  → write the ResearchRun once (write-once; a rerun must reproduce RUN_FIELDS, including `routes`)
```

**Anchor eligibility.** A publication file is a diagnostic anchor event only if **all** of these hold:
1. It is in `observations/`, and its bytes match its manifest (status `published`, SHA256 equal).
2. Its manifest records it as an active publication. Legacy Wind manifests count as active under the genesis record.
3. At least one of its rows belongs to a route that is active at the file's own `as_of` T, evaluated with
   `route_at(·, T)`.

**Never anchors:**
- candidate publications (`candidates/`);
- any file whose rows all belong to routes not active at its own T;
- unverified files.

A pre-activation candidate publication therefore **can never become an anchor later**, because rule 3 is evaluated
at that file's own time, not at the time of the question. Naming such a file with `--anchor` fails with
`ANCHOR_NOT_ELIGIBLE`.

**Selection and comparison.**
- **Default anchor.** The newest eligible anchor, ordered by `(as_of, stem)`.
- **Explicit anchor.** `--anchor <provider>_<run_id>`. `--snapshot <wind run_id>` stays as an alias for Wind anchors.
- **Previous anchor.** The newest eligible anchor with `as_of < T`, from any provider. The two runs are compared as
  today. `compare` annotates input-route changes and lists which providers published in between.
- **Several anchors.** Several providers publishing on one day give several anchors, each its own deterministic run.
  Runs are cheap, write-once and reproducible.

**The five concepts, kept distinct.**

| Concept | What it is | What it is not |
|---|---|---|
| provider publication file | one provider's verified output from one run | not a research snapshot; not complete |
| observation store | all public observation files plus all verified private publication files, append-only | not filtered by route or time |
| diagnostic anchor event | an eligible active publication; it names the run and fixes T | not the information set |
| diagnostic as_of (T) | the anchor's latest `retrieved_at` (unchanged from Phase 2) | not "now"; not the activation time |
| complete information set | the store, filtered by availability at T and by `route_at(·, T)`, then `as_of(T)`; hashed by `information_set_sha256` | not limited to the anchor's provider; it includes, say, the latest Wind property rows at or before T |

**Preserved.**
- Publication files and ResearchRuns are append-only and write-once.
- `available_at = retrieved_at` for private rows.
- `store.as_of` is unchanged.
- Nothing is reconstructed as a pseudo-vintage.
- A run with no earlier eligible anchor reports its comparison as NOT_EVALUABLE, exactly as today.

## 17. Explicitly not proposed

- A data platform, database, queue, plug-in registry or scheduler service.
- Automatic or staleness-driven fallback.
- A licensing or entitlement platform. The route `access` block is four statuses and a citation. `source_class` stays
  per metric, not per route.
- A general derivation framework.
- Renaming `cn_cpi_consensus_wind` / `cn_ppi_consensus_wind`. They *are* Wind's product, and they are inputs of the
  hashed X1 definition.
- Any change to `private_signals.yaml`, the research contract, H0–H4, evidence tests or terminal rules.
- Routing for public metrics that have neither a `wind:` contract nor `sources:`.
- Reclassifying any metric's redistribution. That needs a written decision under data-policy rule 2.

## 18. Smallest change set for V1.2.1, in order

This starts only after the operational baseline is green ([plan, step 0](v1.2.1-implementation-plan.md#order-of-work)).

1. **`store.py`:**
   - add `SourceRoute`, `AccessPolicy`, `RouteChange`, `Metric.sources` and `Metric.route_history`;
   - add `route_at`;
   - add the Wind shim, active only when `metric.wind is not None`;
   - add the load-time checks: the single-file route-history rules (2–4 in §5) and the gates G1, G2, G3 and G5;
   - move the Wind enums to `wind.py`.

   Also in the core change, wherever that change decides it belongs (a loader alone cannot do it): the mechanism that
   enforces cross-version append-only integrity of `route_history` (§5, rule 1). The retroactivity guard (step 4) is in
   addition to it, not a substitute.
2. **`signals.py:186-187`:** the input metric must be `private_only` and routed, and every route its history names
   must pass G1 and G2 (C1). Signal hashes are unaffected.
3. **`normalize.py`:** lift these from `wind.py`, without the Wind literals:
   - the row builder, `validate_rows` and the drift checks;
   - the shared month-end rule with its coverage guard;
   - `publish(…, at)`, which splits rows into `observations/` and `candidates/`;
   - `select_active(obs, metrics, at)`.
4. **`diagnose.py`:**
   - anchor discovery and eligibility (§16), and verified-only loading of both directories (C2, C8);
   - `select_active` at T before `as_of`;
   - `anchor` and `routes` in the run document, `routes` in `RUN_FIELDS` with the legacy-genesis rule, and the
     retroactivity guard (C12);
   - route-change notes in `compare`.

   Also apply `select_active` in the private `check` and `evaluate` paths.
5. **`cli.py`:** `refresh-private --provider`, Wind opt-in, `diagnose-private --anchor` (with `--snapshot` as an
   alias), and the generic `runtime` manifest block.
6. **Adapters** for the Tier A routes only, as candidates
   ([plan](v1.2.1-implementation-plan.md)). Activations follow only as separate reviewed route-history records once
   their gates pass.
7. **Tests** from §15; reword the C9 assertions.
8. **Docs:** data-policy wording, the binding note, and retiring C11.

## 19. Implementation status (V1.2.1 core)

*Added after the core landed (PR #9, 2026-10-06). Sections 0-18 are unchanged; this section only records status.*

**Built, in the order of section 18:**

| Step | Status | Where |
|---|---|---|
| 1. route model, `route_at`, Wind shim, load-time rules and gates G1, G2, G3, G5; enums moved to `wind.py` | done | `store.py`, `wind.py` |
| 1b. cross-version append-only integrity of `route_history` (rule 1) | done | `checks.route_history_audit`, an extension of E4 (the git-history audit of immutable files); also a pre-write guard in `diagnose-private` (`ROUTE_HISTORY_REWRITTEN`) |
| 2. signal eligibility without a provider name | done | `signals.eligible_signal_input` |
| 3. shared normalization, publication and selection | done | `normalize.py` (extracted from `wind.py`, not copied) |
| 4. diagnostics: anchors, verified-only loading, route filter before `as_of` (also private `check`, `evaluate`, `fill-claims`), `anchor` and `routes` in the run, `routes` in `RUN_FIELDS`, legacy-genesis rule, retroactivity guard | done | `diagnose.py`, `cli.py` |
| 5. `refresh-private --provider`, Wind as explicit opt-in, generic `runtime` manifest block, `diagnose-private --anchor` with `--snapshot` as an alias | done | `cli.py`, `wind.py`, `normalize.py` |
| 6. adapters for the Tier A routes | **not started** | the next phase |
| 7. tests of section 15 | done | `tests/test_routing.py`, `test_route_history_audit.py`, `test_provider_diagnose.py` |
| 8. docs: the binding note, retiring C11 | done (C11: `cn_cgb10y.source_fallback` removed) | |
| 8b. docs: data-policy wording | **deferred, accepted** | see below |

**Where the built core is stricter than, or refines, the text above** (none changes a signal, a threshold or a stored run):

1. **Activation is an event, never a schedule (rule 5).** A non-genesis record may not be dated after the moment the
   dictionary is loaded, and every non-genesis record must cite a non-empty `decision`. So the last record is always in
   force and equals `route_at(metric, now)`, which is what makes the "route active **now**" gates (G3, G5) well defined.
   The loader reads the wall clock for this one check; a record that passes can never fail later, so replay is unaffected.
2. **A named route's identity is frozen across versions.** A history record names only a provider. The audit also freezes,
   from the version that first names a route, its `provider`, `series_key`, `equivalence` and `aggregate`: editing one
   would change what the old record means while the record stayed put. Evidence texts, expected metadata, `collect`,
   `params` and the present-tense `access` block remain editable. A changed definition is a new route with its own
   activation record.
3. **The retroactivity guard compares the whole recorded route** (`provider`, `series_key`, `equivalence`, `effective_at`),
   not provider and time alone. A legacy run (no `routes`) is compared with the genesis state, whose equivalence is
   `EXACT` by definition, not read back from the current dictionary.
4. **The static route contract (section 8, load time) is provider-neutral.** For every declared route, Wind's included:
   `aggregate` is `month_end` or absent; `month_end` needs metric frequency M and provider frequency D; an unaggregated
   route's `expected.freq`, if declared, equals the metric's; each of `name`, `freq`, `unit` is either pinned or a
   declared `known_gap` (never both); a second view (`same_series_as`) names an earlier routed metric whose route of the
   same provider has the same `series_key` and `expected`, itself names no owner, and differs in `aggregate`. Raw provider
   unit labels are not compared with the canonical unit: an adapter maps its own vocabulary. `wind.validate_contracts`
   keeps only what is Wind-specific (tools, code formats, query groups).
5. **The month-end coverage guard** also accepts an adapter-stated `covered_through` date. The literal rule ("a later month
   must appear in the batch") rejects real Wind data such as a series ending 30 Sep retrieved 1 Oct Beijing; a downloaded
   file states no such date and still needs a later month.
6. **Provider match is case-insensitive** (`source.lower() == provider`), because legacy Wind rows are labelled `Wind`.
7. **`refresh-private`.** `--provider P [P ...]` runs the named adapters in order. Wind spends paid credits, so a bare
   `refresh-private` does not run it: it exits 1 with `NO_PROVIDER_SELECTED` and makes no call. With no `--provider`
   only `default` adapters run, and only if they have a route active now or a collected candidate whose
   `automated_retrieval` is `permitted`; no adapter is a default today. The adapter table in `cli.py` is the whole
   registry. New Wind manifests carry the generic `runtime: {kind, version, fingerprints, expected, ...}` block instead of
   `skill`; legacy manifests are read as they are (`normalize.runtime_version`).

**Accepted deferral.** *Data-policy wording* (`docs/data-policy.md` rules 2, 3 and 6, from "Wind-derived" to "licensed or
private-route-derived"). It changes no behaviour, and Wind is the only private provider, so the present wording is still
correct. Rewording the policy before any non-Wind route has a recorded access decision would read as covering routes whose
terms are unresolved (CFETS, CSI). **Named follow-up F-POLICY:** the pull request that records the first non-Wind private
route's access decision rewords the three rules (substance unchanged), before that route's activation record.

**Nothing in the core blocks the adapters.** An adapter still needs its own `series_key`, `validation: PASSED` with a
recorded comparison, a permitted `access` policy and, separately, a reviewed activation record.
