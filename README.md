# LoomLedger

**The factory is two things: a ledger and a family tree.**

Stock is never stored — it is the sum of an append-only ledger (`stock_move`). Every physical thing (yarn lot, greige roll, finished roll) is a node in a family tree (`lot_lineage`). Inventory, traceability, defect root cause, recall, true cost, delay impact and the buyer portal are all *derived* from those two tables — in PostgreSQL.

**Start here:** [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md) (who does what, with prompts) · [`CLAUDE.md`](CLAUDE.md) (rules & architecture) · [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) (endpoints) · [`docs/FRONTEND_CONTEXT.md`](docs/FRONTEND_CONTEXT.md) (context pack for chat LLMs)

---

## Quick start

Frontend only (mock data, no database needed):
```bash
cd frontend && npm install && npm run dev  # http://localhost:5173 · owner@everest.test / demo1234
```

Database + tests:
```bash
docker compose up -d                       # PostgreSQL 16 with loomledger + loomledger_test
python -m venv .venv && source .venv/bin/activate   # Windows Git Bash: .venv/Scripts/activate · PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt            # backend + tests (incl. pydantic-settings)

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger_test
./scripts/reset_demo.sh                    # creates the DB if missing, migrates from scratch, seeds the Y-112 scenario
python -m pytest -v                        # golden test + ledger invariants + API tests
docker compose exec -T db psql -U postgres -d loomledger < docs/demo.sql   # the whole demo as raw SQL (no local psql needed)
python -m scripts.export_mocks             # regenerate docs/api-mocks (the API contract) - resets DATABASE_URL!
```

Run it:
```bash
uvicorn app.main:app --port 8000           # backend, docs at http://localhost:8000/docs
cd frontend && cp .env.example .env.local  # then set VITE_USE_MOCKS=false in .env.local
npm run dev                                # http://localhost:5173 against the real backend
./scripts/reset_demo.sh --rehearsal        # private end-to-end check on loomledger_rehearsal + its own backend :8001
```

Without Docker: any PostgreSQL **14+** with the `btree_gist` and `pgcrypto` contrib extensions; `reset_demo` creates the demo
database, and the test database once with `python -m scripts.ensure_db "$TEST_DATABASE_URL"`. With a local `psql`,
`psql "$DATABASE_URL" -f docs/demo.sql` works too.
PowerShell: `$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger"` and
`$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger_test"`, then `.\scripts\reset_demo.ps1` instead of the .sh script.
Presenting: [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md).

`TEST_DATABASE_URL` is the test database (default `loomledger_test`, created empty by `docker compose`).
pytest seeds it automatically: its schema is dropped, migrated and seeded on every run — never point it at the demo DB.

## Layout

```
db/migrations/001_core.sql               tables, enums, composite FKs, exclusion constraints, indexes
db/migrations/002_ledger_guards.sql      append-only ledger, quarantine + stock guards, audit, LISTEN/NOTIFY
db/migrations/003_traceability.sql       ancestors/descendants (recursive CTEs), time travel, roll custody, FIND CAUSE, recall scope
db/migrations/004_costing_impact.sql     true cost roll-up, working-day calendar, recall impact, apply_recall
db/migrations/005_floor_portal_balance.sql  floor board, availability, mass balance, buyer portal
db/migrations/006-009_*.sql              floor NOTIFY payload, production rules, Shade Guard, dispatch guard
db/migrate.py                            applies migrations once each, in order, each in its own transaction
seed/scenario.py                         THE SINGLE SOURCE OF TRUTH for every demo number
seed/seed.py                             deterministic seed built only from scenario.py
tests/test_golden_y112.py                the demo, executed end to end
tests/test_ledger_invariants.py          what the database refuses, and what must always add up
docs/demo.sql                            the 5-minute demo as SQL (Act 1 → month-end)
docs/api-mocks/*.json                    real API responses exported from the seeded DB (the contract)
scripts/export_mocks.py                  regenerates docs/api-mocks
frontend/                                React + Vite + TS + Tailwind v4 skeleton with mock mode
app/                                     FastAPI backend (CLAUDE.md §6, endpoints in docs/API_CONTRACT.md)
scripts/demo_smoke.py, reset_demo.*      the whole demo over HTTP; reset / rehearse (see docs/DEMO_RUNBOOK.md)
```

---

## The canonical Y-112 scenario (locked)

Change these numbers **only** in `seed/scenario.py`. The seed, the golden test and the demo all read from it.
Moving the demo day (`./scripts/reset_demo.sh --anchor 2026-10-12`) shifts dates but no other number.

**Y-112** — 330 kg of 40s cotton from Kaveri Yarn Traders, woven into **12 Navy Twill rolls × 50 m = 600 m**.

| Roll | Custody | Order |
|---|---|---|
| R-1201, R-1202, R-1203 | rejected at QC (colour mismatch) | SO-0412 |
| R-1204, R-1205 | passed QC, **already dispatched** to Meridian Apparels | SO-0412 |
| R-1206 | passed QC, in store | SO-0412 |
| R-1207, R-1208 | passed QC, in store | SO-0419 |
| R-1209, R-1210, R-1211 | awaiting QC | SO-0419 |
| R-1212 | on Loom 5 right now | SO-0419 |

142.8 kg of unused Y-112 yarn is still in the Yarn Store — this is what you try (and fail) to issue on stage.

### Act 2 · Find Cause (rolls R-1201..R-1203)

| Factor | Bad / inspected through it | Rate | Rate elsewhere | Lift | Verdict |
|---|---|---|---|---|---|
| **Yarn Lot Y-112** | 3 / 8 | **37.50%** | 4.00% | 9.38× | **root_cause** |
| Dye Vat 3 | 3 / 33 | 9.09% | 5.33% | 1.71× | coincidental |
| Night Shift B | 3 / 43 | 6.98% | 6.15% | 1.13× | coincidental |
| Day Shift A | 7 / 108 | 6.48% | — | — | no_comparison |
| Loom 2 | covers 2 of 3 | 17.65% | 4.40% | 4.01× | partial |

> "Every bad roll went through Dye Vat 3 — but so did 30 good ones. The system points to the yarn, not the vat."
> If asked about Loom 2: "It looks suspicious, but R-1202 was woven on Loom 5, so it can't explain all three."

Root cause = covers **every** selected rejected roll **and** the highest lift (rate through ÷ rate elsewhere), with lift ≥ 3.

### Act 3 · Recall

9 rolls at risk (3 passed in store, 3 awaiting QC, 1 on the loom, **2 already at Meridian Apparels**) + the 3 rejected.
`apply_recall()` in one transaction: freezes statuses, moves all in-custody stock into the Quarantine Cage, re-promises both orders, and posts buyer messages.

The terminal moment (from `docs/demo.sql`):
```
ERROR:  stock movement blocked: lot Y-112 is quarantined
HINT:   Quarantined stock can only go to quarantine, scrap, or back to the supplier.
```

### Act 4 · Impact panel

| | |
|---|---|
| Rolls affected | 12 (3 rejected + **9 at risk**) |
| Orders affected | 2 (SO-0412, SO-0419) |
| Buyers affected | 2 · **1 already holding goods** (2 rolls) |
| Remake required | 600 m |
| Bottleneck | weaving, 250 m/day |
| Additional delay | **3 working days** — `600 ÷ 250 = 2.4 → ceil = 3` |
| Loss already incurred (3 rejected) | ₹22,488 |
| Newly exposed by recall (6 in factory + 1 WIP + 2 at customer) | ₹64,024 |
| Quarantined yarn, recoverable via supplier claim (142.8 kg) | ₹37,128 |
| **Total exposure** | **₹1,23,640** |

Per order (remake joins the weaving queue in promise-date order):

| Order | Buyer | Remake | Cumulative | Delay | Promised → New |
|---|---|---|---|---|---|
| SO-0412 | Meridian Apparels | 300 m | 300 m | 2 days | 14 Oct → **16 Oct** |
| SO-0419 | Coastline Garments | 300 m | 600 m | 3 days | 17 Oct → **21 Oct** |

(The mill works Monday–Saturday; dates shown for demo day 10 Oct 2026.)

**Cost of one finished Y-112 roll = ₹7,496** = yarn 15.6 kg × ₹260 (₹4,056) + loom 6 h × ₹220 (₹1,320) + weaver 6 h × ₹95 (₹570) + ⅙ of the dye batch (vat 6 h × ₹650 + dyer 6 h × ₹100 + ₹4,800 chemicals = ₹9,300 → ₹1,550). The roll still on the loom carries yarn only (₹4,056): conversion cost is absorbed when the run completes.

### Month-end · mass balance

Yarn is weighed, fabric is measured: **kg = m × width × GSM / 1000**.
Issued 1,545.9 kg = fabric 1,410.0 + recorded waste 56.4 + on the looms 62.4 (4 rolls being woven right now) + **unaccounted 17.1 kg (1.11%)** — and **all of it is on Loom 3 (6.64% of what it was issued)**.

### Buyer links (deterministic for the demo; production links use `gen_random_uuid()`)

| Order | Path |
|---|---|
| SO-0412 · Meridian Apparels | `/track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d` |
| SO-0419 · Coastline Garments | `/track/8b1ab95b-593a-5796-b23b-a7bdfc0cddd4` |
| SO-0405 · Saffron Home Linen | `/track/c1be7402-1f2c-5c3e-8c64-3eae94fdc565` |
| SO-0398 · Bluebird Uniforms | `/track/bd8db814-f234-55a9-a001-d0f6af766b89` |

Seeded logins (all `demo1234`): `owner@`, `store@`, `floor@`, `qc@`, `accounts@everest.test`.

---

## What the database enforces (whatever the client)

| Rule | How | Error |
|---|---|---|
| Ledger history can't be rewritten | `BEFORE UPDATE/DELETE/TRUNCATE` trigger | `LL003` |
| Quarantined stock can't move (except to quarantine, scrap, supplier) | `guard_stock_move()` trigger | `LL001` |
| No location goes negative; concurrent issues serialised | same trigger + `pg_advisory_xact_lock(lot)` | `LL002` |
| A machine can't run two jobs at once | `EXCLUDE USING gist (machine_id =, tstzrange &&)` | `23P01` |
| A roll can't ship twice | `UNIQUE (lot_id)` on `dispatch_line` | `23505` |
| Retries / double-clicks / offline sync never double-post | `UNIQUE (idempotency_key)` | `23505` |
| A run's stage matches its machine (no dyeing on a loom) | composite FK `(machine_id, stage)` | `23503` |
| A lot's kind matches its product; greige comes from weaving, finished from dyeing | composite FKs + CHECK | `23503` / `23514` |
| Only finished fabric can be sold | composite FK on `order_line` | `23503` |
| A failed inspection must name a defect | CHECK | `23514` |
| Genealogy walks can't loop on bad data | `CYCLE` clause in recursive CTEs | — |

**Suggested API mapping:** `LL001 → 409 "Lot is quarantined"`, `LL002 → 422 "Not enough stock"`, `LL003 → 405`, `23P01 → 409 "Machine already booked"`, `23505 on idempotency_key → 200 with the original result` (a replay is not an error), other `235xx → 422` with a field message.

## Functions the API exposes

| Screen | Call |
|---|---|
| Floor board | `v_machine_now`, `floor_output(day)`, `machine_availability(from, to)`, `LISTEN loomledger_floor` |
| Find Cause | `find_cause(rejected_lot_ids[])` |
| Recall | `recall_scope(root)`, `recall_impact(root)`, `recall_order_impact(root)`, `apply_recall(root, reason, user)` |
| Cost | `lot_cost(lot)`, `v_roll_cost` |
| Inventory | `stock_on_hand(as_of)` — pass a past timestamp for time travel; `lot_on_hand(lot, location, as_of)` |
| Month-end | `mass_balance(from, to)`, `v_yarn_unaccounted_by_machine` |
| Buyer portal | `buyer_order_status(token)` → JSON or NULL (answer 404 either way) |
| Live ledger feed | `LISTEN loomledger_ledger` |

## Before quoting performance numbers

Quote only what was measured: [`docs/BENCHMARK.md`](docs/BENCHMARK.md) (`./scripts/reset_demo.sh && python -m scripts.benchmark`,
`EXPLAIN (ANALYZE, BUFFERS)` of every demo query, read-only). Re-run it after the data grows.

## Team ownership

See [`CLAUDE.md` §11](CLAUDE.md).

Rule: **if the golden test is red, nobody merges.**
