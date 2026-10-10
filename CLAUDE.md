# CLAUDE.md — LoomLedger

Read this whole file before doing anything in this repo. It is the team's shared brain.

## 1. What we are building

**LoomLedger** — Odoo Hackathon finals (24 h), problem statement: *Textile Manufacturing System* for "Everest Textile Mills".

Core idea: **a factory is two things — a ledger and a family tree.**
- **Ledger** (`stock_move`): stock is never stored; it is the sum of append-only movements between locations.
- **Family tree** (`lot_lineage`): every physical thing (yarn lot → greige roll → finished roll) knows its parents.
Everything else — inventory, traceability, defect root cause, recall, true cost per roll, delivery delay, buyer portal — is **derived** from those two tables, mostly inside PostgreSQL.

**The demo story (everything we build serves it):**
1. **Act 1 – Normal day.** Live floor board: 4 of 6 looms weaving (Looms 1, 4, 5, 6), yarn arriving; Loom 4 breaks down live.
2. **Act 2 – Something's wrong.** QC rejects 3 rolls (colour mismatch). *Find Cause* walks their ancestry and compares defect rates: **Yarn Lot Y-112 (37.5% vs 4.0% elsewhere) is the root cause; Dye Vat 3 and Night Shift B are coincidental.**
3. **Act 3 – Contain it.** *Recall* finds 9 more at-risk rolls, **2 already delivered** to a buyer. Apply recall → everything quarantined → trying to issue Y-112 yarn is **refused by PostgreSQL itself** (shown in the UI and in psql).
4. **Act 4 – Business impact.** 2 orders, 2 buyers, 600 m to remake, **600 ÷ 250 = 2.4 → 3 working days** delay, **₹1,23,640 total exposure**. The buyer's phone shows the new date.
5. **Close.** Month-end mass balance (1.11% yarn unaccounted — all on Loom 3), true cost per roll, tests passing.

Closing line: *"The factory knew it had a defect. LoomLedger knows where it came from, what it touched, what it cost, and what to do next."*

## 2. Golden rules (non-negotiable)

1. **`seed/scenario.py` is the single source of truth for every demo number.** Never hardcode 37.5, 600, 3, ₹1,23,640 etc. in code or UI — read them from the API. To change a number, change `scenario.py`, then fix the seed/tests.
2. **`tests/test_golden_y112.py` must stay green.** If it's red, nobody merges. Run `python -m pytest` before every backend PR.
3. **Never edit a migration that is already on `main`.** Add a new numbered file (`006_...sql`). Never change the ledger to allow UPDATE/DELETE.
4. **`docs/api-mocks/*.json` is the API contract.** Backend responses must match those shapes exactly. Frontend reads data only through `frontend/src/api/client.ts`.
5. **Business rules live in the database** (constraints, triggers, functions). The API must not re-implement or bypass them. Every request that writes = exactly one transaction.
6. **Parameterized SQL only.** Never build SQL with f-strings or string concatenation from user input.
7. **No AI chatbot features, no third-party APIs** (no Firebase, no email/SMS services, no hosted charts). Libraries are fine.
8. **Don't touch files another person owns** (see §11) without telling them. Small, focused PRs.
9. **Never invent performance numbers.** Only quote what `EXPLAIN ANALYZE` measured.

## 3. Repo map

```
CLAUDE.md                       this file
README.md                       setup + locked numbers + what the DB enforces
docs/API_CONTRACT.md            every endpoint, owner, request, response file, error codes
docs/api-mocks/*.json           REAL responses exported from the seeded DB (the contract)
docs/TEAM_PLAN.md               who does what, hour by hour, with starter prompts
docs/FRONTEND_CONTEXT.md        compact rules pack for chat LLMs (ChatGPT/Sonnet) building screens
docs/demo.sql                   the whole demo as raw SQL (and the psql "terminal moment")
db/migrations/00N_*.sql         schema; applied in order by db/migrate.py
db/migrate.py                   python -m db.migrate [--reset]
seed/scenario.py                canonical numbers + independent expected values
seed/seed.py                    deterministic seed (python -m seed.seed [--anchor YYYY-MM-DD])
scripts/export_mocks.py         regenerate docs/api-mocks from the DB
scripts/reset_demo.sh / .ps1    wipe + reseed (run before every rehearsal); --smoke / -Smoke = reset → demo smoke → reset
scripts/demo_smoke.py           walks the whole demo story over HTTP + ws against a running backend (✓/✗ per step)
scripts/benchmark.py            EXPLAIN (ANALYZE, BUFFERS) of the demo queries, read-only → docs/BENCHMARK.md
tests/                          DB tests: golden chain + invariants (pytest)
app/                            FastAPI backend (to be built — §6)
frontend/                       React + Vite + TS + Tailwind v4 (skeleton built — §7)
```

## 4. Commands

```bash
# setup
pip install -r requirements.txt                        # includes pydantic-settings (backend config)

# database
docker compose up -d                                   # Postgres 16 on :5432 (loomledger + loomledger_test)
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger_test
./scripts/reset_demo.sh                                # migrate from scratch + seed
./scripts/reset_demo.sh --smoke [URL]                  # REHEARSAL: reset → walk Acts 1–4 + close over HTTP/ws → reset
                                                       #   (backend must be running; exit ≠ 0 = the demo is broken)
python -m scripts.demo_smoke [URL]                     # just the walk-through; refuses (exit 2) unless the DB is fresh
./scripts/reset_demo.sh --rehearsal                    # PRIVATE rehearsal: loomledger_rehearsal (auto-created) + own backend on :8001
                                                       #   → reset → smoke → stop → reset. Never touches the demo DB or :8000
./scripts/reset_demo.sh --db-url URL                   # reset any other database (created if missing)
./scripts/reset_demo.sh && python -m scripts.benchmark # measured query timings + index use → docs/BENCHMARK.md (rule 9: quote only these)
python -m pytest -q                                    # golden + invariants + api tests (wipes + reseeds the TEST db itself)
psql "$DATABASE_URL" -f docs/demo.sql                  # run the demo in SQL
python -m scripts.export_mocks                         # regenerate the API contract files

# backend (once app/ exists)
uvicorn app.main:app --reload --port 8000              # docs at http://localhost:8000/docs

# frontend
cd frontend && npm install
npm run dev                                            # http://localhost:5173 (mock data by default)
npm run build                                          # typecheck + production build — must pass before a PR
# real backend: create frontend/.env.local with VITE_USE_MOCKS=false
# teammate's backend over LAN: they run `uvicorn app.main:app --host 0.0.0.0 --port 8000` (allow port 8000 in their firewall);
#   you copy frontend/.env.example to .env.local, set VITE_API_TARGET=http://<their LAN IP>:8000, restart npm run dev
```

Windows users: run the Python commands in PowerShell with `$env:DATABASE_URL="..."` and
`$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger_test"`, and use `.\scripts\reset_demo.ps1` (private rehearsal: `.\scripts\reset_demo.ps1 -Rehearsal`, other DB: `-DatabaseUrl URL`; if scripts are blocked:
`powershell -ExecutionPolicy Bypass -File .\scripts\reset_demo.ps1 -Smoke`) instead of the .sh script.

Test database: `docker compose` creates the empty `loomledger_test` database (scripts/init-test-db.sql). You never
seed it by hand — the pytest fixtures drop its schema, migrate and seed it automatically (once per module for DB tests,
once per session for `tests/api`). Never point `TEST_DATABASE_URL` at the demo database.

**Shared demo DB:** `loomledger` is what teammates test against through the backend on :8000 — don't reset, seed,
smoke or export mocks against it while they're using it. Rehearse with `--rehearsal` / `-Rehearsal` (DB
`loomledger_rehearsal`, backend :8001); `scripts/export_mocks.py` also resets whatever `DATABASE_URL` points at.

## 5. Database (done — extend, don't rewrite)

PostgreSQL 16 (14+ works). Extensions: `btree_gist`, `pgcrypto`. Session timezone is set to `Asia/Kolkata`.

| Migration | Contents |
|---|---|
| 001_core | enums, masters, orders, `process_run` (exclusion constraint: no machine double-booking), `lot`, `lot_lineage`, `stock_move` (ledger), QC, dispatch, invoices, recall, floor state log, attendance, buyer links, audit log, indexes |
| 002_ledger_guards | append-only ledger (`LL003`), quarantine guard (`LL001`), stock sufficiency + advisory lock (`LL002`), audit triggers, `pg_notify` on machine state + ledger |
| 003_traceability | `lot_ancestors`, `lot_descendants` (recursive CTE with CYCLE), `lot_on_hand`, `stock_on_hand(as_of)` = time travel, `v_latest_qc`, `v_roll_custody`, `v_roll_factor`, **`find_cause(lot_ids[])`**, `recall_scope(root)` |
| 004_costing_impact | **`lot_cost(lot)`** recursive cost roll-up, `v_roll_cost`, `add_working_days` (Mon–Sat), **`recall_order_impact(root)`**, **`recall_impact(root)`**, **`apply_recall(root, reason, user)`** (idempotent) |
| 005_floor_portal_balance | `v_machine_now`, `floor_output(day)`, `machine_availability(from,to)`, `v_yarn_balance_by_run`, **`mass_balance(from,to)`**, `v_yarn_unaccounted_by_machine`, **`buyer_order_status(token)`** |
| 006_floor_notify_payload | `ist_iso(ts)`; `loomledger_floor` NOTIFY payload = `ws_floor_event.json` (adds `machine_code`, `reason`) |
| 007_production_rules | `weaving_yarn_issue_kg(product, m)` (m × width × GSM/1000 × 1.04), `shift_at(ts)` (IST shift calendar) |
| 008_shade_guard | `dispatch.shade_override_reason`; dispatch_line trigger: one dye batch per dispatch unless an override reason is recorded (`LL006`). Merged after 009 — order-independent |
| 009_dispatch_guard | dispatch_line trigger: latest QC must be `pass` (`LL004`), roll reserved for the dispatch's order (`LL005`) |

Conventions for new migrations:
- File `db/migrations/00N_short_name.sql`, one concern per file, comment header explaining *why*.
- Prefer declarative rules (CHECK, FK, composite FK, EXCLUDE, UNIQUE) over triggers; triggers only for cross-row rules.
- New business error → new custom SQLSTATE `LL0xx` + add to the mapping in `docs/API_CONTRACT.md` and `app/errors.py`.
- Every new rule gets a test in `tests/test_ledger_invariants.py` proving the DB refuses bad data.
- Custody/status shown to users must be derived from facts (`v_roll_custody`), not from `lot.status` alone.

Key domain facts: yarn in **kg**, fabric in **m**, bridge `kg = m × width_m × GSM / 1000`. Loom waste 4%. Mill works Mon–Sat. Shift A 08–20, Shift B 20–08. WIP carries material cost only (conversion absorbed at run completion).

## 6. Backend — FastAPI (to build)

Stack: Python 3.11+, FastAPI, psycopg 3 + `psycopg_pool` (no ORM), Pydantic v2, uvicorn, itsdangerous (tokens). Already in `requirements.txt`.

Layout (each module = router → service → repository, nothing skips a layer):
```
app/
  main.py         create app, CORS (http://localhost:5173), include routers, /api/health, exception handlers, request-id middleware
  config.py       Settings from env: DATABASE_URL, SECRET_KEY, TOKEN_TTL_HOURS=12, CORS_ORIGINS
  db.py           ConnectionPool(dict_row, autocommit); get_conn() dependency; `with write_tx(conn):` once per write request
  errors.py       ApiError(code, message, status, hint, fields); map psycopg errors by sqlstate/constraint name (table in API_CONTRACT.md)
  auth.py         POST /api/auth/login (crypt() check in SQL), sign/verify token, require_user, require_role(*roles)
  realtime.py     dedicated LISTEN loomledger_floor connection (thread; reconnects) → Broadcaster → /ws/floor?token=
  modules/<area>/router.py     HTTP only: parse, auth, call service, return schema
  modules/<area>/service.py    business flow + the single transaction
  modules/<area>/repository.py SQL only (calls the DB functions/views); returns dicts
  modules/<area>/schemas.py    Pydantic request/response models (field names = contract keys)
tests/api/        pytest + httpx TestClient: happy path, each error code, contract shape vs docs/api-mocks
```
Areas: `floor`, `inventory`, `production`, `quality`, `trace`, `recalls`, `orders` (incl. dispatch + track), `finance`.

Rules:
- Response JSON must equal the mock file shape. Decimal → float, dates ISO. Use `jsonable_encoder` or explicit schema.
- Validate input with Pydantic (`Field(gt=0)`, regex for codes like `^Y-\d{3,}$`, enums); return `422 VALIDATION_FAILED` with `fields`.
- Idempotent writes: catch unique violation on `idempotency_key` → return the original result (200).
- Roles: store → receipts; floor_supervisor → floor/production; qc → inspections, recalls; accounts → finance; owner → everything.
- Log one line per request with request id, method, path, status, ms. Never return SQL text or stack traces to the client.
- Keep handlers thin; a service function should read like the business sentence it implements.

## 7. Frontend — React (skeleton done)

Stack: React 19, Vite, TypeScript 5 (strict), Tailwind CSS v4 (`@tailwindcss/vite`, tokens in `src/index.css` `@theme`), react-router-dom 7, lucide-react icons, recharts for charts. **Ask before adding any other dependency** (for the genealogy graph `@xyflow/react` is pre-approved).

```
frontend/src/
  api/client.ts     api.<area>.<action>() — the ONLY way to call the backend; mock vs real switch (VITE_USE_MOCKS)
  api/mocks.ts      mock implementation serving docs/api-mocks (stateful: recalls.apply() flips to post-recall data)
  api/types.ts      response/request types (mirror the contract)
  api/errors.ts     ApiError {code, message, status, hint, fields}
  components/ui.tsx Button, Card, Badge, StatTile, PageHeader, DataTable, Spinner, EmptyState, ErrorBanner, Loadable, Modal, Field, Input, Select, Textarea
  components/AppShell.tsx  sidebar + top bar (owner: Adithi). Add nav items here + route in App.tsx.
  hooks/useApi.ts   useApi(load, deps) for reads; useAction(fn) for writes
  lib/format.ts     formatINR (₹1,23,640), formatQty, formatPct, formatLift, formatDate, formatDateTime, formatSince, humanize, newIdempotencyKey
  lib/tones.ts      machineStateTone, custodyTone/custodyLabel, lotStatusTone, verdictTone/verdictLabel
  pages/*.tsx       one file per route; placeholders show the spec + live data until replaced
```

Rules:
- Colours only from tokens (`bg-brand`, `text-ok`, `bg-hold-soft`, `border-line`...). Never raw hex or default Tailwind palette colours.
- Status colours always via `lib/tones.ts`. Money via `formatINR`, dates via `formatDate*`. Codes (R-1201, Y-112) in `font-mono`.
- Every data view handles **loading, error (ErrorBanner + retry), empty** — use `<Loadable>`.
- Every form: inline validation before submit, `useAction`, disable while running, show API error message, `newIdempotencyKey()` once per form.
- Layout: page padding comes from AppShell; use `grid gap-6`; cards `Card`; tiles in `grid grid-cols-2 lg:grid-cols-4 gap-4`. Must work at 375 px wide (the buyer page is mobile-first).
- Accessibility: buttons are `<button>`, inputs have labels (`Field`), icon-only buttons have `aria-label`.
- Pattern to copy: `pages/LoginPage.tsx`.

## 8. The canonical numbers (for reference — the API delivers them)

Find Cause on R-1201..R-1203: Y-112 **3/8 = 37.50%** vs 4/100 = **4.00%** → lift 9.38 → root_cause · Dye Vat 3 3/33 = 9.09% vs 5.33% → coincidental · Night Shift B 3/43 = 6.98% vs 6.15% → coincidental · Loom 2 covers 2 of 3 → partial.
Recall Y-112: 12 rolls = 3 rejected + 9 at risk (3 passed in store, 3 awaiting QC, 1 on Loom 5, **2 at Meridian Apparels: R-1204, R-1205**). Orders SO-0412 (14 → 16 Oct, +2) and SO-0419 (17 → 21 Oct, +3).
Money: already lost ₹22,488 · newly exposed ₹64,024 · recoverable yarn 142.8 kg = ₹37,128 · **total ₹1,23,640**. Finished Y-112 roll = ₹7,496.
Floor at demo "now": Looms 1, 4, 6 weaving R-1213-G..R-1215-G (`BUSY_FLOOR`) + Loom 5 weaving R-1212-G; Loom 2 free (the Y-112 refusal), Loom 3 idle.
Mass balance (`expected_mass_balance()`): issued 1,545.9 kg = fabric 1,410.0 + waste 56.4 + on the looms 62.4 + unaccounted 17.1 kg = **1.11%**, all on **Loom 3 (6.64%)**.
Buyer link SO-0412: `/track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d`. Logins: `owner@everest.test` (also store@, floor@, qc@, accounts@), password `demo1234`.

## 9. Definition of done (every task)

- Works against mock data AND (once available) the real API.
- Backend: `python -m pytest -q` green, including the golden test; new endpoint has tests for happy path + each error.
- Frontend: `npm run build` passes (no TS errors); checked at 375 px and 1280 px; loading/error/empty states exist.
- No hardcoded demo numbers; no secrets in code; no console errors.
- Committed on a feature branch with a conventional message and merged by PR.
- CI green on the PR (`.github/workflows/ci.yml`): migrate + seed from scratch, `pytest`, **mocks regenerated from
  the DB equal `docs/api-mocks`** (changed a response shape or the seed? run `python -m scripts.export_mocks` and
  commit the diff), and the frontend `npm ci && npm run build`.

## 10. Git workflow

- `main` is always demo-able. Work on `name/short-topic` branches (`nooman/recall-page`, `adithi/floor-board`).
- Commit small and often (at least every hour): `feat(recall): impact panel`, `fix(api): map LL002 to 422`, `test(db): shade guard`, `docs: ...`.
- Before a PR: `git pull origin main` into your branch, re-run tests/build. Open PR → Sampurna (or Nooman) reviews and squash-merges.
- Never commit `node_modules`, `.env`, `frontend/dist`. Never force-push `main`.
- All four people must have commits on `main` — this is judged.

## 11. Team and ownership

| Person | Tools | Owns |
|---|---|---|
| **Sampurna** | VS Code + Claude Code | repo admin + merges, backend platform (`app/main.py`, `db.py`, `errors.py`, `auth.py`, `realtime.py`), modules `floor`, `inventory`, `production`, `quality`, `orders`, `finance`; integration (switching mocks off); CI |
| **Nooman** | VS Code + Claude Code | the story: modules `trace`, `recalls`, Shade Guard migration; pages `TracePage`, `RecallPage` (incl. genealogy graph); API contract tests; benchmark (late) |
| **Adithi** | ChatGPT / Sonnet / free LLMs | `AppShell.tsx`, `index.css` tokens, pages `FloorBoardPage`, `QualityPage`, `InventoryPage` (time travel), `GateEntryPage`; final UI consistency pass |
| **Dhruva** | ChatGPT / Sonnet / free LLMs | pages `TrackPage` (mobile), `OrdersPage`, `MonthEndPage`; `scripts/floor_simulator.py`; ER diagram; pitch deck + demo script; README screenshots |

Shared files (`App.tsx`, `ui.tsx`, `types.ts`, `client.ts`, `mocks.ts`): small additive changes only, mention them in the PR.

## 12. Working style for Claude Code in this repo

- For anything bigger than one file: state a short plan first, then implement.
- Read the relevant migration / mock JSON / existing component before writing code that depends on it.
- After changes: run the tests or build yourself and fix failures before saying "done".
- Keep explanations short; update `docs/API_CONTRACT.md` and this file when you change a convention.
- If a request conflicts with a golden rule, stop and say so.

## 13. Out of scope (do not build)

Gantt drag-and-drop, offline PWA, three-way PO matching, chatbots/AI features, email/SMS, multi-tenant, dark mode, i18n. If there is time after feature freeze, polish the story instead.
