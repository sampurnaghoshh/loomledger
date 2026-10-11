# LoomLedger · demo runbook

For presenting from the demo laptop (Windows, PowerShell). **Every figure in the demo is read from the screen** — this
runbook deliberately contains none, and nobody types a number on stage. The story and its numbers live in
`seed/scenario.py` and `CLAUDE.md` §1. Click-by-click narration: [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

Login on the laptop for the whole demo: **`owner@everest.test`** / `demo1234` (owner can do every step; other roles
are refused, and the screens hide what a role can't use).

---

## 0. Before the day

- **Demo date. Finals on Sunday 11 Oct 2026 → plain `.\scripts\reset_demo.ps1`, no `-Anchor`.** The story's day
  (`ANCHOR_DATE` in `seed/scenario.py`) is Saturday 10 Oct — the mill's last working day before a Sunday demo. The screens
  follow the mill calendar, not your laptop's date: Quality shows the **latest** rejections, floor output defaults to the
  last working day. Only move the story (`-Anchor <date>`) to a **working day** (Mon–Sat) that is today or earlier.
- **After pulling / merging new code:** `cd frontend; npm install` (new packages: `qrcode`), then
  **`python -m db.migrate`** with `$env:DATABASE_URL` pointing at `loomledger` (adds the new migrations; the reset
  below also does it from scratch), then restart Windows 1 and 2.
- **Private rehearsal, any time:** `.\scripts\reset_demo.ps1 -Rehearsal` — its own database (`loomledger_rehearsal`) and
  backend (:8001); never touches the demo database or :8000. Must end with **`39 ✓  0 ✗`**.
- **Evaluator playground** (a bigger, separate dataset for judges who want to explore): §6.

### Network: laptop + two phones on one hotspot (no venue Wi-Fi needed)

**Plan A — Windows Mobile Hotspot (laptop shares its connection).** Settings → Network & internet → Mobile hotspot → On.
The laptop is then **`192.168.137.1`** on that network (check with `ipconfig`: adapter "Local Area Connection* …").
Both phones join the laptop's hotspot.

**Plan B — a phone's hotspot (if the laptop can't host).** Turn on the hotspot on the *scanner* phone; the laptop and the
owner phone join it. The laptop's address is the IPv4 of "Wireless LAN adapter Wi-Fi" in `ipconfig` (something like
`192.168.43.x` / `172.20.10.x`). Use that address everywhere below instead of `192.168.137.1`.

**Once, as administrator** (PowerShell): let phones reach the frontend —
`New-NetFirewallRule -DisplayName "LoomLedger Vite 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow`.
Phones only talk to Vite (:5173); Vite forwards `/api` and `/ws` to the backend on the laptop.

**QR labels:** laptop → **QR labels** → set **QR link base** to `http://<laptop-ip>:5173` (remembered in this browser) →
**Print labels**, or scan straight off the screen.

### Two phones, two jobs

| Phone | Opens | When |
|---|---|---|
| **Owner phone** (face up on the table) | `http://<laptop-ip>:5173/alerts` → sign in as owner → **Arm alerts** (one short beep = sound works). Volume up, screen timeout "never" (keep-awake needs HTTPS). | Armed **before Act 1**. |
| **Scanner phone** (in the presenter's hand) | Camera app → scan the **R-1204** label → passport (sign in once as owner); the buyer page `http://<laptop-ip>:5173/track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d` in a second tab (no login: the link is the credential; also Orders → SO-0412 → **Copy link**). | Acts 3 and 4. |

## 1. Startup (in this order)

| # | Where | Do | Check |
|---|---|---|---|
| 1 | Docker Desktop | Start it, wait for "Engine running". Then in any PowerShell in the repo: `docker compose up -d` | `docker compose ps` → `db` is `healthy` |
| 2 | **Window 1 · backend** | `cd C:\Dev\loomledger`<br>`.venv\Scripts\Activate.ps1`<br>`$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger"`<br>`uvicorn app.main:app --host 0.0.0.0 --port 8000` (no `--reload` on stage) | http://localhost:8000/api/health → `"status":"ok","db":"ok","realtime":"ok"` |
| 3 | **Window 2 · frontend** | `cd C:\Dev\loomledger\frontend`<br>`frontend\.env.local` must contain `VITE_USE_MOCKS=false` (copy `.env.example` once)<br>**`npm run dev -- --host`** | It prints a `Local:` and a `Network:` URL. The header must **not** show "mock data". |
| 4 | **Window 3 · reset + terminal** | `cd C:\Dev\loomledger; .venv\Scripts\Activate.ps1`<br>`.\scripts\reset_demo.ps1` (no `-Anchor`, see §0) | Ends with "demo day 2026-10-10" and the four `buyer link …` lines |
| 5 | Window 3 | Type the **terminal moment** command (§3) and **don't press Enter** yet | — |
| 6 | Phones | Owner phone: `/alerts` → **Arm alerts**. Scanner phone: passport tab + buyer tab (§0). | Owner phone says **Listening…** |

Optional final check, only when nobody else is using this backend: `.\scripts\reset_demo.ps1 -Smoke` (reset → whole
story over HTTP → reset again). Must print **`39 ✓  0 ✗`**.

**Laptop browser:** http://localhost:5173 → log in as owner. Open tabs: **Floor Board**, **Orders**.

## 2. Click path (read every number from the screen)

| Act | Screen | Click | Show |
|---|---|---|---|
| **1 · Normal day** | **Floor Board** | — | *Machines running* and which looms weave which roll. The run bars are **grey "Woven to plan · due off loom since Sat …"**: the floor as the mill left it on Saturday (the story day) — the data says those rolls are due off the loom; we don't fake the clock. |
| | Floor Board | Loom 4 → **Change state** → *Breakdown*, reason → **Save state** | Live update without refresh; Loom 4's red badge, *Breakdowns* tile. **Owner phone turns amber**: "Loom 4 has stopped" — acknowledge it on the phone. |
| | **Inventory** (optional) | Pick a past time → **View this time** | Stock rebuilt from the ledger at that moment. **Back to now**. |
| **2 · Something's wrong** | **Quality** | **Find cause** on the rejected-rolls banner | Lands on Find Cause with the rejected rolls. |
| | **Find Cause** | — | The headline factor and verdict; the ranked table; why the vat and the shift are coincidental; the genealogy graph. |
| **3 · Contain it** | Scanner phone | Scan **R-1204** | Passport **before**: "AT BUYER (Meridian Apparels)", its family tree back to the yarn lot, QC, true cost, shipment. |
| | Find Cause → **Recall** \<yarn lot\> | **Apply recall** → reason → **Quarantine everything** | Header turns *Quarantined* with the recall code. **Owner phone goes red**: CRITICAL QUALITY RECALL, rolls, buyers, orders, delay, total exposure, the action line (three beeps). |
| | Scanner phone | Refresh the R-1204 passport | **After**: purple "QUARANTINED · AT BUYER", the recall card, promised date struck through → new date. |
| | Recall | **Issue** \<yarn lot\> **to** \<loom\> | Big red *"The database refused"* panel with the SQLSTATE. (It is also written to Admin → **Validation log**.) |
| | **Window 3** | Press **Enter** on the prepared command (§3) | The same refusal from `psql` — PostgreSQL itself, not the UI. |
| **4 · Business impact** | Recall | Scroll | Delay tile + its "a ÷ b = c → ceil" line, money row with *Total exposure*, orders delayed (promised → revised). |
| | **Orders** | — | Both orders delayed; **SO-0419 now says "Yarn short"** — the quarantined yarn no longer counts as usable, so the remake needs new yarn. The progress bars show "to weave … (incl. remakes)". |
| | Scanner phone → buyer tab | Refresh | The buyer's page: new expected date and the message about the delivered rolls. |
| **Close** | **Month-end** | Period: *To date* (default) | Mass balance: issued vs fabric / waste / on the looms; *Unaccounted* and its %; "All of the gap is on …". |
| | Month-end | *True cost per roll* | Per-roll yarn / machine / labour / chemicals; quarantined / recalled badges. |
| | Month-end | *Profit & loss* (story month) | **It shows a loss — say why, honestly:** a full month of wages is booked while only the shipments made so far are invoiced; the recall exposure is shown separately as contingent, not hidden in the result. |
| | **Workforce** | Register / Wages | Who worked which shift; the wage run that feeds the P&L. |
| | Header / Inventory | — | The **Yarn low** banner: usable yarn is below the reorder level after the quarantine. |

Closing line: *"The factory knew it had a defect. LoomLedger knows where it came from, what it touched, what it cost, and what to do next."*

## 3. The terminal moment (Window 3, from the repo folder, **after** Apply recall)

```powershell
docker compose exec db psql -U postgres -d loomledger -c "INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key) SELECT l.id, f.id, t.id, 20, 'issue', 'stage-demo-1' FROM lot l, location f, location t WHERE l.code = 'Y-112' AND f.code = 'QUARANTINE' AND t.code = 'PRODUCTION';"
```

Expected (tested): `ERROR:  stock movement blocked: lot Y-112 is quarantined` and the `HINT` line. It's the same
statement as in `docs/demo.sql`. Nothing is written, so it can be run again. Don't add `2>&1` (PowerShell wraps the
message in red noise).

## 4. Between rehearsals

1. Window 3: `.\scripts\reset_demo.ps1` (no `-Anchor` for the Sunday finals).
2. Browser: **F5** on every tab (the Recall page keeps what it last loaded). Phones: reload, and **re-arm** the owner phone.
3. Leave Windows 1 and 2 running — the reset works under a running backend.

## 5. If something breaks

| Symptom | Fix |
|---|---|
| Pages say *"Can't reach the LoomLedger server"* | Window 1 died → start uvicorn again (§1 step 2). Check Docker Desktop is running and `docker compose ps` shows `db` healthy. |
| Header shows **mock data** | `frontend\.env.local` is missing `VITE_USE_MOCKS=false` → fix it, then stop and restart `npm run dev -- --host`. |
| Floor board doesn't update live | F5 the Floor Board (the socket connects on page load). Check http://localhost:8000/api/health says `"realtime":"ok"`; if it says `connecting`, restart Window 1. |
| Numbers look wrong, Recall already says *Quarantined*, buyer page already delayed | A previous run left state behind → `.\scripts\reset_demo.ps1`, then F5 everything. |
| No "rolls rejected" banner on Quality | The rejections are gone (someone re-inspected, or the DB isn't seeded) → `.\scripts\reset_demo.ps1`, F5. The banner shows the latest rejection day, so the calendar date doesn't matter. |
| Floor shows looms "running" for over a day | Expected on a Sunday: the floor is as the mill left it on Saturday (see §0). Say "this is the floor as of the last shift". |
| Sent to the login page | Session expired (12 h) → log in as owner again. |
| An action says *Your role is not allowed* | You're not logged in as owner → Log out, log in as `owner@everest.test`. |
| Recall page: *"No idle loom right now"* | A loom's state was changed → Floor Board → set Loom 2 (or any loom) to *Idle*, or reset. |
| Terminal: `service "db" is not running` | Run it from `C:\Dev\loomledger` (the folder that started Docker), and `docker compose up -d`. |
| Terminal: *insufficient stock* instead of *quarantined* | The recall isn't applied yet → Apply recall in the UI first. |
| Phone can't open the link | Same Wi-Fi? Use the **Network** URL from Window 2 / `ipconfig`. Firewall: allow Node.js on private networks. |
| Venue Wi-Fi dead | Turn on the phone's hotspot, connect the laptop to it, re-check `ipconfig`, use the new Network URL. Everything else runs locally. If the phone still can't connect, show the buyer page on the laptop: browser DevTools → device toolbar (375 px). |
| `npm run dev` fails with *Cannot find module* | `cd frontend; npm install`, then restart Window 2. |
| Backend won't start: *address already in use* | Something else holds :8000 → close the old Window 1 (or `Get-NetTCPConnection -LocalPort 8000` to find it). |
| Everything is down and there's no time | Last resort: `VITE_USE_MOCKS=true` in `frontend\.env.local`, restart Window 2 — the screens run on recorded data (no live database, no terminal moment). |
| Owner phone shows nothing on Recall / breakdown | It must be **armed** (tap *Arm alerts*) and say *Listening…*; signed in as owner or qc. Phone screen locked → it may miss the beep; reload `/alerts` and arm again. Alerts are live only: nothing from before arming is shown. |
| Phone can't open `http://<laptop-ip>:5173` | Same hotspot? Firewall rule for 5173 (§0)? Window 2 started with `npm run dev -- --host`? `ipconfig` for the right address. |
| QR scan opens the wrong address | QR labels → **QR link base** = `http://<laptop-ip>:5173`, reprint / rescan. |
| A page says "not allowed" / a button is missing | You're not owner. Log out, log in as `owner@everest.test` (buttons are hidden for roles that can't use them). |
| 500 errors right after a reset | Restart Window 1 once (a reset recreates the schema under the running backend). |

## 6. Evaluator playground (separate database, separate ports — the demo is never touched)

For evaluators who want to click around with more than the story: the same story **plus ~300 rolls of history**
(15 buyers, 60 more orders in every status, QC pass / rework / reject with every defect type, dispatches, invoices,
payments, attendance), all dated in the two months *before* the story so nothing in the story moves.

```powershell
# 1. build (or rebuild) loomledger_eval — starts nothing, never touches loomledger
.\scripts\reset_demo.ps1 -Eval                                   # bash: ./scripts/reset_demo.sh --eval

# 2. Window A — a backend on :8002 that only sees loomledger_eval
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger_eval"
uvicorn app.main:app --port 8002

# 3. Window B — a frontend on :5174 that talks to it (real data, not mocks)
cd frontend
$env:VITE_USE_MOCKS="false"; $env:VITE_API_TARGET="http://localhost:8002"
npm run dev -- --port 5174 --strictPort                         # http://localhost:5174 · owner@everest.test / demo1234
```

Notes: the eval rolls are `R-2001`…`R-2300` (yarn `Y-301`…`Y-312`, orders `SO-0301`…). Numbers that compare the story
against *everything else* (find-cause rates, mass balance to date, earlier months' P&L) are different here — that is
expected; the demo database keeps the locked numbers. Reset the playground any time with `.\scripts\reset_demo.ps1 -Eval`.
