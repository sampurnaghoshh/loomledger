# LoomLedger — team plan (24 hours)

**H0 = the moment Sampurna pushes this repo to GitHub.** Times below are hours after H0.

| Person | Tools | Role in one line |
|---|---|---|
| Sampurna | VS Code + Claude Code | Repo owner + backend platform + operations APIs + integration |
| Nooman | VS Code + Claude Code | The story: Find Cause + Recall screens AND their APIs, genealogy graph, Shade Guard |
| Adithi | ChatGPT / Sonnet / free LLMs | Frontend lead: shell + Floor Board, Quality, Inventory (time travel), Gate Entry |
| Dhruva | ChatGPT / Sonnet / free LLMs | Buyer page (mobile), Orders, Month-end, floor simulator, ER diagram, pitch |

Why this split: Claude Code can read and run the whole repo, so Sampurna and Nooman take the work that spans backend + database + frontend. Chat LLMs work best on one self-contained file at a time, so Adithi and Dhruva each own whole screens and build them against **mock data that is a real copy of the database** — they never wait for the backend.

---

## Shared timeline

| Hours | Sampurna | Nooman | Adithi | Dhruva |
|---|---|---|---|---|
| 0 – 0.5 | Create GitHub repo, push, invite all | Setup (§Setup B) | Setup (§Setup A) | Setup (§Setup A) |
| 0.5 – 2.5 | S1 backend platform | N1 Find Cause page (mock) | A1 Floor Board | D1 Buyer tracking page |
| 2.5 – 5 | S2 floor + realtime, S3 inventory | N2 Recall page (mock) | A1 finish, A2 Quality | D2 Orders page, D3 ER diagram |
| 5 – 8 | S4 quality, S5 orders + track, S6 finance | N3 trace + recall APIs + contract tests | A3 Inventory + time travel | D4 Month-end |
| 8 – 10 | S7 production (weaving start/finish) | N4 genealogy graph | A4 Gate Entry | D5 floor simulator |
| **10 – 12** | **INTEGRATION: everyone switches `VITE_USE_MOCKS=false`, fixes mismatches** | | | |
| 12 – 18 | fixes, CI, seed polish · sleep 90 min in pairs (Sampurna+Adithi, then Nooman+Dhruva) | N5 Shade Guard + dispatch | A5 UI consistency pass | D6 pitch deck + demo script |
| 18 – 21 | benchmark support, bug bash | N6 benchmark (real numbers) | polish + mobile check | README screenshots, rehearse |
| **21** | **FEATURE FREEZE** — only fixes after this | | | |
| 21 – 23 | reset_demo, run demo 3× end to end, final merges | | | |
| 23 – 24 | buffer | | | |

Stand-up every 3 hours (5 minutes): what's merged, what's blocked, what's next. Merge to `main` at least every 2–3 hours each.

---

## What is in the repo already (built and tested)

- **Database** (`db/migrations`): the whole data model + all the smart logic — Find Cause, recall, impact, cost, mass balance, time travel, buyer status — as PostgreSQL functions. 20 tests prove the numbers.
- **Seed** (`seed/`): a fake but realistic mill with the Y-112 story baked in. Same numbers every time.
- **API contract** (`docs/API_CONTRACT.md` + `docs/api-mocks/*.json`): every endpoint and its exact response, copied from the real database.
- **Frontend skeleton** (`frontend/`): login, sidebar, routes, UI kit, API client with mock mode. Every page exists as a placeholder that shows *what to build* and *the data it gets*. You replace the placeholder with the real screen.
- **Not built yet**: the FastAPI backend (`app/`) and the real screens — that's the next 24 hours.

---

## Setup A — Adithi & Dhruva (frontend only, ~15 min)

You do **not** need Python, Docker or a database to start.

1. Install **Node.js 22 LTS** (nodejs.org), **Git** (git-scm.com), **VS Code**.
2. Accept the GitHub invite from Sampurna. Then in a terminal:
   ```bash
   git clone https://github.com/<sampurna-username>/loomledger.git
   cd loomledger/frontend
   npm install
   npm run dev
   ```
3. Open http://localhost:5173 → log in with `owner@everest.test` / `demo1234`. You should see the sidebar and a "mock data" pill.
4. Open your page (e.g. Floor Board). The placeholder shows the to-do list and the exact JSON your page receives.

**Git routine (do this for every piece of work):**
```bash
git checkout main && git pull
git checkout -b adithi/floor-board          # your-name/topic
# ...paste the LLM's file, check it in the browser...
cd frontend && npm run build                # must finish without errors
git add frontend/src/pages/FloorBoardPage.tsx
git commit -m "feat(floor): machine grid with live state"
git push -u origin adithi/floor-board
```
Then on GitHub click **Compare & pull request** → create → tell Sampurna. Commit at least every hour.

**How to work with ChatGPT / Sonnet (important):**
- Start every new chat by uploading/pasting, in this order: `docs/FRONTEND_CONTEXT.md`, `frontend/src/api/types.ts`, `frontend/src/components/ui.tsx`, the mock JSON files for your page (from `docs/api-mocks/`), and the current page file.
- Then paste the task prompt from your section below.
- Paste the returned **whole file** over the old one. If `npm run dev` or the browser shows an error, paste the exact error + the file back into the chat: *"Fix this error. Return the complete file."*
- If the chat gets long or confused, start a **new chat** with the same context pack + your latest file.
- Never let the LLM add new npm packages, change `ui.tsx`/`client.ts`, or hardcode numbers. If it needs something missing, ask Sampurna or Nooman.

## Setup B — Sampurna & Nooman (full stack, ~20 min)

1. Install Node 22, Python 3.11+, Git, Docker Desktop (or local PostgreSQL 16), VS Code + Claude Code.
2. Sampurna only — create the repo:
   ```bash
   unzip loomledger.zip && cd loomledger
   git init && git add . && git commit -m "chore: database foundation, Y-112 scenario, API contract, frontend skeleton"
   git branch -M main
   git remote add origin https://github.com/<you>/loomledger.git && git push -u origin main
   ```
   On GitHub: Settings → Collaborators → invite Nooman, Adithi, Dhruva. (Optional: Settings → Branches → require a PR to merge into `main`.)
3. Both:
   ```bash
   git clone ... && cd loomledger
   docker compose up -d
   python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger   # Windows: $env:DATABASE_URL="..."
   export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loomledger_test
   python -m seed.seed
   python -m pytest -q                                        # expect: 20 passed
   cd frontend && npm install && npm run dev
   ```
4. Open the repo folder in VS Code and start Claude Code. It reads `CLAUDE.md` automatically. Start each task with the prompt from your section. One task per Claude Code session works best; `/clear` between tasks.

---

## Sampurna — tasks and prompts

**S1 · Backend platform (H0.5–2.5)** — branch `sampurna/api-platform`
> Read CLAUDE.md (§6) and docs/API_CONTRACT.md. Build the backend platform in `app/`: main.py (CORS for localhost:5173, /api/health, request-id + timing log middleware, exception handlers producing the error envelope), config.py, db.py (psycopg_pool with dict_row, get_conn dependency), errors.py (ApiError + mapping of psycopg errors by sqlstate and constraint name exactly as in API_CONTRACT.md), auth.py (POST /api/auth/login checking the password with crypt() in SQL, itsdangerous signed tokens with expiry, require_user and require_role dependencies). Add tests in tests/api/ with httpx TestClient: login ok, wrong password 401, missing token 401, and one test per error mapping (LL001, LL002, 23P01). Plan first, then implement, then run pytest until green. Do not build the feature modules yet.

**S2 · Floor + realtime (H2.5–4)** — `sampurna/floor-api`
> Build app/modules/floor (router/service/repository/schemas) per docs/API_CONTRACT.md: GET /api/floor/machines, /output, /availability, POST /api/floor/machines/{code}/state (close open state row + open new one in one transaction, 404 unknown machine, 422 bad state). Add app/realtime.py: an async listener on `loomledger_floor` that broadcasts to all /ws/floor WebSocket clients (enrich the payload with machine_code). Contract tests: each GET equals docs/api-mocks/floor_*.json after a fresh seed.

**S3 · Inventory (H4–5)** — GET /api/inventory/stock (+ `as_of`), POST /api/inventory/receipts (goods_receipt + yarn lot + receipt move in one transaction, idempotency replay returns 200 with the original result, validation 422). Tests.

**S4 · Quality (H5–6)** — GET queue, GET rejections, POST inspections (reject also moves FG-STORE → REJECT-BAY). Tests.

**S5 · Orders + buyer portal (H6–7)** — GET /api/orders, GET /api/track/{token} (public, 404 envelope for bad/expired token). Tests.

**S6 · Finance (H7–8)** — GET mass-balance, GET roll-costs?order_code=. Contract tests.

**S7 · Production (H8–10)** — POST /api/production/weaving-runs and /finish exactly as in the contract (yarn issue kg from GSM × width × 1.04; shift from current IST hour; LOT_QUARANTINED must surface as 409 — this is the stage demo). Tests including the Y-112-after-recall refusal.

**S8 · Integration (H10–12)** — run backend + frontend with `VITE_USE_MOCKS=false`; open every page; fix shape mismatches in the backend (the mocks are the contract). Add GitHub Actions for `npm run build` next to the existing pytest workflow.

Ongoing: review and merge PRs every ~2 hours; keep `main` demo-able; run `./scripts/reset_demo.sh` before rehearsals.

## Nooman — tasks and prompts

**N1 · Find Cause page, mock mode (H0.5–2.5)** — `nooman/find-cause-page`
> Read CLAUDE.md §7 and §8, docs/api-mocks/trace_find_cause.json and trace_graph_ancestors.json. Replace frontend/src/pages/TracePage.tsx with the real Find Cause screen as specified in its placeholder: selected rejected rolls from `?lots=`, a headline card for the top factor (rate through vs elsewhere, lift), the ranked factor table with verdict badges and two comparison bars per row, a one-line explanation why Dye Vat 3 is coincidental (computed from the data, not hardcoded), and a CTA to /recall/<root lot>. Use only the UI kit, tones and format helpers. Run npm run build.

**N2 · Recall page, mock mode (H2.5–5)** — `nooman/recall-page`
> Replace RecallPage.tsx: impact panel (StatTiles incl. the money split already lost / newly exposed / recoverable / total), the calculation line from `calculation.display`, rolls table grouped by custody, orders table promised → revised, "Apply recall" with a confirm Modal → api.recalls.apply → applied state, and a "Try issuing Y-112 to Loom 2" button that calls api.production.startWeaving and shows the LOT_QUARANTINED error prominently. This is the most important screen of the demo — make it clear at a glance from 3 metres away.

**N3 · Trace + recall APIs (H5–8)** — after S1 is merged — `nooman/trace-api`
> Build app/modules/trace and app/modules/recalls per docs/API_CONTRACT.md (find-cause, graph up, descendants, recall preview, apply recall — idempotent). Write contract tests comparing each response with docs/api-mocks (ignore applied_at and event timestamps). Write tests/api/test_story.py that runs the whole Y-112 story through HTTP: find cause → preview → apply → weaving run with Y-112 returns 409 LOT_QUARANTINED → /api/track shows the revised date.

**N4 · Genealogy graph (H8–10)** — add `@xyflow/react`; a left-to-right graph on TracePage (yarn → greige → finished) with machine + shift on each node, the root cause highlighted, and on RecallPage the descendants of Y-112 coloured by custody.

**N5 · Shade Guard + dispatch (H12–15)** — migration 006: function that, for an order line and a list of rolls, returns the distinct dye batches; POST /api/dispatches refuses mixed batches with 409 SHADE_MISMATCH unless `shade_override_reason` is given (recorded in order_event). DB test + API test.

**N6 · Benchmark (H18–21)** — script that bulk-generates ~200k ledger rows / 5k+ rolls in a separate DB, runs `EXPLAIN ANALYZE` on find_cause, recall_scope and stock_on_hand before and after any index/materialized view change. Put the **measured** numbers in README. If `v_roll_factor` is slow, materialize it.

## Adithi — tasks and prompts (paste the context pack first, see Setup A)

Your files: `pages/FloorBoardPage.tsx`, `pages/QualityPage.tsx`, `pages/InventoryPage.tsx`, `pages/GateEntryPage.tsx`, and later `components/AppShell.tsx` + `index.css` tokens.

**A1 · Floor Board (H0.5–4)** — attach `floor_machines.json`, `floor_output.json`, `floor_availability.json`, `ws_floor_event.json`, current `FloorBoardPage.tsx`.
> Write the complete file frontend/src/pages/FloorBoardPage.tsx. It is the live factory floor of a textile mill, shown first in the demo, so it must look alive and calm. Requirements: (1) PageHeader "Floor Board" with today's date. (2) Stat tiles: running, idle, breakdown counts (from api.floor.machines), metres produced today (sum of api.floor.output), average availability (api.floor.availability). (3) Machines grouped by stage (Weaving, Dyeing, Spinning) as cards in a responsive grid: machine name, state Badge using machineStateTone, "since" using formatSince(state_since), and when present the current lot (font-mono) and order. Breakdown cards get a bad-soft background. (4) Live updates: useEffect → api.floor.subscribe(event => update that machine's state and state_since in local state; if state is breakdown show a dismissible red banner "Loom 4 broke down — <reason>"); unsubscribe on unmount. (5) Each card has a small "Change state" button opening a Modal with a Select of states and a reason Input → api.floor.setState → update the card. Handle loading/error/empty with Loadable. Follow every rule in FRONTEND_CONTEXT.md and return the complete file.

**A2 · Quality (H4–5.5)** — attach `quality_queue.json`, `quality_rejections.json`.
> Write the complete QualityPage.tsx: (1) if there are rejections, a prominent alert strip "N rolls rejected — <defect>" with a Button "Find cause" that navigates to `/trace?lots=` + the rejected lot codes joined by commas (useNavigate). (2) "Awaiting inspection" DataTable (roll, product, dye batch, dyed on, dyed at, order); clicking a row opens a Modal to record the result: Pass / Rework / Reject as three toggle buttons; when not Pass, defect type Select (colour_mismatch, hole, uneven_weave, oil_stain, missing_pick) and defect metres Input are required; submit with useAction(api.quality.inspect); on success close, remove the row, show a small success message. (3) "Recent rejections" DataTable. Loading/error/empty states everywhere.

**A3 · Inventory with time travel (H5.5–8)** — attach `inventory_stock_now.json`, `inventory_stock_as_of.json`.
> Write the complete InventoryPage.tsx: stock grouped by location (one Card per location with a DataTable: lot, kind, product, qty with unit), filter chips for lot kind, and a TIME TRAVEL bar: a datetime-local input plus a range slider over the last 21 days; when set, call api.inventory.stock(isoWithOffset) and show a hold-tone banner "Viewing stock as of <formatDateTime>" with a "Back to now" button. Quarantine Cage rows use the hold tone. Totals per location in kg and m.

**A4 · Gate Entry (H8–10)**
> Write the complete GateEntryPage.tsx: a yarn receipt form (supplier Select: SUP-KAV Kaveri Yarn Traders / SUP-NAR Narmada Spinners; lot code; kg; price per kg; vehicle no.; challan no.). Inline validation (required fields, numbers > 0, lot code must match /^Y-\d{3,}$/). Create the idempotency key once with useState(newIdempotencyKey). Submit with useAction(api.inventory.receive). Show field errors from error.fields if present. On success show a confirmation Card with the receipt code and a "Record another" button that resets the form and creates a new key. Show the computed total value (kg × price) with formatINR as the user types.

**A5 · UI consistency pass (H12–18)** — go through every page at 375 px and 1280 px: same spacing, same header style, no raw colours, empty/loading/error states present. Polish `AppShell.tsx` (active state, mobile menu). Write down anything broken in other people's pages and send it to them.

## Dhruva — tasks and prompts (paste the context pack first, see Setup A)

Your files: `pages/TrackPage.tsx`, `pages/OrdersPage.tsx`, `pages/MonthEndPage.tsx`, `scripts/floor_simulator.py`, `docs/er-diagram.png`, the pitch deck.

**D1 · Buyer tracking page, mobile first (H0.5–3)** — attach `track_SO-0412_before.json`, `track_SO-0412_after.json`, `error_not_found.json`, current `TrackPage.tsx`.
> Write the complete frontend/src/pages/TrackPage.tsx. This is a PUBLIC page a buyer opens on their phone from a link (no login, no sidebar). Design for 375 px first, centred max-w-md on desktop. Read `token` with useParams and load api.orders.track(token). Show: mill name "Everest Textile Mills" small at top; order code (font-mono), buyer and product; a big "Expected dispatch" date (formatDate(expected_date)); if `delayed`, an amber (warn-soft) banner "Was <promised_date>, now <expected_date>" plus the newest update message; a segmented progress bar of progress (dispatched / ready / quality check / weaving / on hold) with a legend showing metres for each (formatQty) against ordered_m; an "Updates" timeline (newest first) with formatDateTime. If the error code is NOT_FOUND show a friendly full-page card "This tracking link is invalid or has expired". Test with /track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d and /track/abc.

**D2 · Orders (H3–4.5)** — attach `orders.json`.
> Write the complete OrdersPage.tsx: PageHeader "Orders"; DataTable with code (font-mono), buyer, product, ordered metres, promised date, expected date (revised_promise_date shown in text-bad with a "+N days" Badge when it is later than promised), status Badge, and a progress mini-bar from progress; an actions column with "Buyer page" (opens /track/<tracking_token> in a new tab) and "Copy link" (navigator.clipboard, shows "Copied"). Stat tiles above: open orders, metres ordered, metres dispatched, orders delayed.

**D3 · ER diagram (H4.5–5.5)** — give the LLM `db/migrations/001_core.sql` and ask: *"Convert this PostgreSQL schema to DBML for dbdiagram.io. Include every table, column type, primary key and foreign key (including composite foreign keys). Group tables: Masters, Ledger & Genealogy, Production, Quality, Sales & Money, Floor, Portal & Audit."* Paste into dbdiagram.io, arrange it neatly (ledger and lineage in the centre), export PNG to `docs/er-diagram.png`, commit.

**D4 · Month-end (H5.5–8)** — attach `finance_mass_balance.json`, `finance_roll_costs_SO-0412.json`.
> Write the complete MonthEndPage.tsx with two Cards. (1) "Where did the yarn go?": tiles for received, issued, fabric, recorded waste, on the loom, UNACCOUNTED (kg + %, bad tone); a horizontal stacked bar (recharts BarChart, layout vertical) splitting issued yarn into fabric / waste / on loom / unaccounted using CSS variables var(--color-ok) etc. for fills; a note "kg = metres × width × GSM ÷ 1000"; a by-machine DataTable sorted by unaccounted with the top row highlighted. (2) "True cost per roll": an order Select (SO-0412, SO-0419, SO-0405, SO-0398) → api.finance.rollCosts(order); DataTable (roll, custody Badge, material, machine, labour, chemicals, total, ₹/m) and a stacked bar chart of the four cost components per roll; totals row.

**D5 · Floor simulator (H8–10)** — needs Sampurna's floor API (S2). Python standard library only.
> Write scripts/floor_simulator.py using only the Python standard library (urllib.request, json, random, time, argparse). It logs in to http://localhost:8000/api/auth/login as floor@everest.test / demo1234, then every N seconds (default 6) picks a machine from GET /api/floor/machines and changes its state with POST /api/floor/machines/{code}/state using weighted probabilities (running 70%, idle 15%, changeover 10%, breakdown 5%, with realistic reasons). A `--demo` flag runs a fixed script instead: set all looms running, and at 60 seconds put LOOM-4 into breakdown with reason "Warp beam bearing failure". Print one readable line per change. Handle server errors without crashing (retry after 3 s).

**D6 · Pitch + demo script (H12–21)** — 6–8 slides max: problem (notebooks & phone calls), the insight (ledger + family tree), live demo (no slides during it), architecture (ER diagram + "the database enforces it" table from README), what we measured (tests, benchmark), close line. Write `docs/demo_script.md`: who clicks what, what is said, timing per act (use README "canonical scenario" numbers — they come from the API, never type them on slides differently). Lead the rehearsals.

---

## Rules for everyone

- Only change files you own; for shared files (`App.tsx`, `ui.tsx`, `types.ts`, `client.ts`, `mocks.ts`) ask first and keep changes tiny.
- Numbers on screen always come from the API. Slides must match the README numbers exactly.
- Before every PR: frontend `npm run build`; backend `python -m pytest -q`.
- If you're blocked for more than 20 minutes, say so in the group chat.
- Sleep in pairs; one Claude Code person is always awake.
