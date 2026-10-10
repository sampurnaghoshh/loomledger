# LoomLedger · demo runbook

For presenting from the demo laptop (Windows, PowerShell). Every figure in the demo is **read from the screen** — this
runbook deliberately contains none. The story and its numbers live in `seed/scenario.py` and `CLAUDE.md` §1.

Login for the whole demo: **`owner@everest.test`** / `demo1234` (owner can do every step; other roles get 403 on some).

---

## 0. Before the day

- **Demo date.** The seed puts the story on the demo day in `seed/scenario.py` (`ANCHOR_DATE`). The Quality page only
  raises its "N rolls rejected …" banner for rejections made **today**, so if you present on any other date, reset with
  that date: `.\scripts\reset_demo.ps1 -Anchor (Get-Date -Format yyyy-MM-dd)` (dates shift, no other number changes).
- **After pulling new code:** `cd frontend; npm install` (new packages, e.g. the genealogy graph), then restart the windows below.
- **Private rehearsal, any time:** `.\scripts\reset_demo.ps1 -Rehearsal` — its own database (`loomledger_rehearsal`) and
  backend (:8001); never touches the demo database or :8000. Must end with `0 ✗`.
- Windows firewall: allow **Python** and **Node.js** on private networks (the phone reaches the laptop on :5173).

## 1. Startup (in this order)

| # | Where | Do | Check |
|---|---|---|---|
| 1 | Docker Desktop | Start it, wait for "Engine running". Then in any PowerShell in the repo: `docker compose up -d` | `docker compose ps` → `db` is `healthy` |
| 2 | **Window 1 · backend** | `cd C:\Dev\loomledger`<br>`.venv\Scripts\Activate.ps1`<br>`$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger"`<br>`uvicorn app.main:app --host 0.0.0.0 --port 8000` (no `--reload` on stage) | http://localhost:8000/api/health → `"status":"ok","db":"ok","realtime":"ok"` |
| 3 | **Window 2 · frontend** | `cd C:\Dev\loomledger\frontend`<br>`frontend\.env.local` must contain `VITE_USE_MOCKS=false` (copy `.env.example` once)<br>`npm run dev -- --host` | It prints a `Local:` and a `Network:` URL — note the **Network** one for the phone. The header must **not** show "mock data". |
| 4 | **Window 3 · reset + terminal** | `cd C:\Dev\loomledger; .venv\Scripts\Activate.ps1`<br>`.\scripts\reset_demo.ps1` (add `-Anchor …` if needed, see §0) | Ends with the four `buyer link …` lines |
| 5 | Window 3 | Type the **terminal moment** command (§3) and **don't press Enter** yet | — |

Optional final check, only when nobody else is using this backend: `.\scripts\reset_demo.ps1 -Smoke` (reset → whole
story over HTTP → reset again). Must print `0 ✗`.

**Browser:** http://localhost:5173 → log in as owner. Open tabs: **Floor Board**, **Orders**.
**Phone (buyer):** same Wi-Fi as the laptop. Open the **Network** URL + the SO-0412 track path:
`http://<laptop-ip>:5173/track/4155711b-d0c4-5f02-a2b5-bfd8dd09045d` (also on Orders → SO-0412 → **Copy link**;
`ipconfig` shows the laptop's IPv4). No login on the phone — the link is the credential.

## 2. Click path

| Act | Screen | Click | Show (read from the screen) |
|---|---|---|---|
| **1 · Normal day** | **Floor Board** | — | The *Machines running* tile and which looms are weaving, each with its roll. |
| | Floor Board | Loom 4 → **Change state** → *Breakdown*, reason → **Save state** | The board updates live (no refresh) and shows the breakdown notice — pushed from PostgreSQL over the WebSocket. |
| | **Inventory** (optional) | Pick a past time → **View this time** | "Viewing stock as of …" — stock reconstructed from the ledger. **Back to now**. |
| **2 · Something's wrong** | **Quality** | **Find cause** on the "rolls rejected for colour mismatch" banner | Lands on Find Cause with the rejected rolls. |
| | **Find Cause** | — | The headline factor and its verdict; the ranked table; "Why these are not the cause" (the vat and the shift); the genealogy graph. |
| **3 · Contain it** | Find Cause | **Recall** \<yarn lot\> (red button under the headline) | Recall preview: rolls affected, at the buyer, orders, delay, money. |
| | **Recall** | **Apply recall** → reason → **Quarantine everything** | Header turns to *Quarantined* with the recall code. |
| | Recall | **Issue** \<yarn lot\> **to** \<loom\> | Big red *"The database refused"* panel with the error and SQLSTATE. |
| | **Window 3** | Press **Enter** on the prepared command (§3) | The same refusal from `psql` — PostgreSQL itself, not the UI. |
| **4 · Business impact** | Recall | Scroll | Delay tile + its "a ÷ b = c → ceil" line, the money row with *Total exposure*, *Orders delayed* (promised → revised). |
| | **Orders** | SO-0412 → **Buyer link** (or the phone) | The buyer's page: new expected date and the message about the delivered rolls. Refresh the phone. |
| **Close** | **Month-end** | Period: *To date* (default) | Issued vs fabric/waste/on the looms; *Unaccounted* and its %; the sentence "All of the gap is on …"; the bar chart. |
| | Month-end | *True cost per roll* (defaults to the delayed order) | Per-roll yarn / machine / labour / chemicals and the quarantined / recalled badges. |

Closing line: *"The factory knew it had a defect. LoomLedger knows where it came from, what it touched, what it cost, and what to do next."*

## 3. The terminal moment (Window 3, from the repo folder, **after** Apply recall)

```powershell
docker compose exec db psql -U postgres -d loomledger -c "INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key) SELECT l.id, f.id, t.id, 20, 'issue', 'stage-demo-1' FROM lot l, location f, location t WHERE l.code = 'Y-112' AND f.code = 'QUARANTINE' AND t.code = 'PRODUCTION';"
```

Expected (tested): `ERROR:  stock movement blocked: lot Y-112 is quarantined` and the `HINT` line. It's the same
statement as in `docs/demo.sql`. Nothing is written, so it can be run again. Don't add `2>&1` (PowerShell wraps the
message in red noise).

## 4. Between rehearsals

1. Window 3: `.\scripts\reset_demo.ps1` (same `-Anchor` as before, if you used one).
2. Browser: **F5** on every tab (the Recall page keeps what it last loaded). Phone: refresh.
3. Leave Windows 1 and 2 running — the reset works under a running backend.

## 5. If something breaks

| Symptom | Fix |
|---|---|
| Pages say *"Can't reach the LoomLedger server"* | Window 1 died → start uvicorn again (§1 step 2). Check Docker Desktop is running and `docker compose ps` shows `db` healthy. |
| Header shows **mock data** | `frontend\.env.local` is missing `VITE_USE_MOCKS=false` → fix it, then stop and restart `npm run dev -- --host`. |
| Floor board doesn't update live | F5 the Floor Board (the socket connects on page load). Check http://localhost:8000/api/health says `"realtime":"ok"`; if it says `connecting`, restart Window 1. |
| Numbers look wrong, Recall already says *Quarantined*, buyer page already delayed | A previous run left state behind → `.\scripts\reset_demo.ps1`, then F5 everything. |
| No "rolls rejected" banner on Quality | Presenting on a different date than the seed's demo day → reset with `-Anchor (Get-Date -Format yyyy-MM-dd)`. |
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
