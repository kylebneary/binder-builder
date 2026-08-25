# 01 — Architecture

## Shape

Local-first monolith. One FastAPI process, one SQLite file, one React SPA. No queue, no Redis, no
containers required to run it. The scheduled price ingest is a cron entry calling a CLI command.

```
┌─────────────────────────────────────────────────────┐
│ React SPA (Vite + TS + TanStack Query + Tailwind)   │
└────────────────────────┬────────────────────────────┘
                         │ REST /api/v1
┌────────────────────────┴────────────────────────────┐
│ FastAPI                                             │
│  api/      routers, Pydantic schemas                │
│  services/ business logic (UI-agnostic)             │
│  sim/      NumPy Monte Carlo + analytic oracle      │
│  binder/   layout engine + ReportLab export         │
│  ingest/   source adapters                          │
│  models/   SQLAlchemy 2.0                           │
└────────────────────────┬────────────────────────────┘
                         │
              SQLite (Postgres-compatible SQL)
                         ▲
        ┌────────────────┴──────────────┐
        │ CLI (Typer) — ingest, sim,    │
        │ export. Cron target.          │
        └───────────────────────────────┘
```

## Why this shape

- **Local-first** because the data is personal, the price feed is a daily file, and nothing here
  benefits from a server. It also means no hosting cost and no auth in v1.
- **Business logic in services, not routers**, because the optimizer must be callable from the CLI
  and from tests without spinning up HTTP.
- **SQLite now, Postgres later** — the schema is deliberately portable. If price history grows past
  what SQLite handles comfortably, changing `DATABASE_URL` is the whole migration.
- **A real SPA rather than server-rendered templates** because the binder designer is a
  drag-and-drop canvas and the set browser is a large virtualised grid. Both are genuinely
  client-side problems.

## Layer rules

| Layer | May import | Must not |
|---|---|---|
| `api/` | services, schemas | ORM models directly, `sim/` |
| `services/` | models, sim, binder, ingest | FastAPI, `Request` |
| `sim/` | nothing project-specific except plain dataclasses | ORM models, DB session |
| `ingest/` | models, httpx | services |

`sim/` taking plain dataclasses rather than ORM objects is deliberate: the simulator runs hundreds
of thousands of trials and must not hold a DB session or lazy-load anything. The service layer
loads the goal, prices, and pull-rate profile into NumPy arrays once, then calls a pure function.

## Ingest adapters

```python
class CardSource(Protocol):
    def fetch_sets(self) -> Iterable[SetDTO]: ...
    def fetch_cards(self, set_ref: str) -> Iterable[CardDTO]: ...

class PriceSource(Protocol):
    name: str
    def fetch_prices(self, as_of: date) -> Iterable[PricePointDTO]: ...
```

Implementations: `TcgCsvPriceSource`, `PokemonTcgCardSource`, `PokemonTcgPriceSource` (fallback),
`ManualCsvPriceSource`. Adding a paid provider means one new file and one config line.

All adapters are **idempotent upserts** on natural keys. Re-running today's ingest twice must not
create duplicate rows or double-count anything.

## Caching and jobs

- Card metadata: refresh on demand only. It changes when a set releases.
- Prices: daily at 20:30 UTC (tcgcsv publishes ~20:00 UTC). A `--backfill` flag pulls archived
  daily bundles for price history.
- Simulation results: memoised on a hash of `(goal_id, owned_hash, price_date, profile_version,
  params, seed)` in `simulation_run`. The UI checks the cache before re-simulating.
- Card images: hotlink from the official CDN; cache thumbnails locally for the binder canvas only.

## Configuration

Pydantic Settings, `.env` file, `.env.example` committed. Keys: `DATABASE_URL`,
`POKEMONTCG_API_KEY` (optional), `TCGCSV_BASE_URL`, `DATA_DIR`, `SIM_DEFAULT_TRIALS`,
`SIM_MAX_TRIALS`, `IMAGE_CACHE_DIR`.

## Error handling

Ingest failures must be loud and partial-safe: wrap each set in its own transaction, log the
failures, continue, and finish with a summary of what did not land. A price ingest that half-fails
silently is the single most dangerous failure mode in this system, because the optimizer will
happily produce a confident answer from stale or missing prices. Every optimizer result carries the
`observed_on` date of the prices it used, and the UI displays it.

## Testing

- `sim/` — the heaviest coverage. See the test list in `docs/04-optimizer-spec.md`.
- `ingest/` — recorded fixtures of real API responses (a few real sets, checked in), no live calls
  in CI.
- `binder/` — overlap invariants, template validation, PDF dimensional correctness.
- `api/` — smoke tests per route via `TestClient`.

## Deferred deliberately

Auth, multi-user, background workers, Docker, WebSockets, other TCGs, mobile. Each is a real cost
and none is needed to answer the question this tool exists to answer.
