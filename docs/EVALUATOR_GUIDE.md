# LoomLedger · evaluator guide

A playground with **the demo story plus ~300 rolls of history** (15 buyers, ~60 more orders in every status, QC
pass / rework / reject with every defect type, dispatches, invoices, payments, attendance) — in its own database,
on its own ports. Break anything you like; the presentation database is never touched.

## Open it

```powershell
docker compose up -d                                             # PostgreSQL
.\scripts\reset_demo.ps1 -Eval                                   # builds loomledger_eval (bash: ./scripts/reset_demo.sh --eval)

# Window A · backend on :8002
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/loomledger_eval"
uvicorn app.main:app --port 8002

# Window B · frontend on :5174
cd frontend; $env:VITE_USE_MOCKS="false"; $env:VITE_API_TARGET="http://localhost:8002"
npm run dev -- --port 5174 --strictPort                         # → http://localhost:5174
```

Start over at any time: `.\scripts\reset_demo.ps1 -Eval`. API docs: http://localhost:8002/docs.

## Who can do what (password `demo1234` for all)

| Login | Role | Can | Can't (button hidden, API answers 403) |
|---|---|---|---|
| `owner@everest.test` | owner | everything, incl. **Users & roles** | — |
| `store@everest.test` | store | gate entry (yarn receipts), dispatch rolls | inspect, recall, finance, users |
| `floor@everest.test` | floor supervisor | machine states, start weaving, attendance register | dispatch, inspect, finance |
| `qc@everest.test` | qc | QC inspections, apply recalls, owner alerts, validation log | dispatch, finance, users |
| `accounts@everest.test` | accounts | month-end, P&L, invoices, payments, wages | floor, QC, recalls |

Everyone signed in can read the floor, stock, quality lists, trace, recall preview, orders and **Records**.
The full matrix is on **Admin → Roles & permissions** — it is the table the API checks on every request.

## Things to try

1. **Lists** — *Records*: search (e.g. a buyer), sort by any header (click twice for descending), filter
   (where / kind / latest QC / status), page through "1–25 of …". The URL keeps the state: copy it to a colleague.
2. **Skip a phase** — as `qc@`: *Quality → Inspect by roll code* → `R-2018-G` (a greige roll). Refused:
   **PHASE_SKIPPED**, missing phase *dyeing*. Then *Admin → Validation log*: your attempt, who, when, why.
3. **A quarantined roll** — apply a recall (Recall page as `qc@`/owner), then try to issue that yarn lot to a loom:
   PostgreSQL refuses it (`LL001`), and the refusal lands in the validation log too.
4. **Dispatch before QC** — as `store@`: *Orders → Dispatch rolls → show all reserved rolls* → pick one awaiting QC:
   refused (`NOT_QC_PASSED`).
5. **Double-click a form** — submit a gate entry or a payment twice quickly: the second request carries the same
   idempotency key and returns the first result — nothing is written twice.
6. **Users & roles** — as owner: change `store@` to *qc*, sign in as store@ in another browser and watch the menu change;
   deactivate a user (their open session stops working at once); every change is in the audit log.
7. **The last-owner guard** — as owner: try to demote or deactivate yourself → **LAST_OWNER** / **SELF_DEACTIVATION**.
   The database enforces it even from raw SQL.
8. **Time travel** — *Inventory → pick a past moment → View this time*: stock rebuilt from the ledger as it was then.
9. **A roll's whole life** — *Records → Rolls* → click any roll code: the passport (family tree, QC, true cost, order,
   dispatch, recall). *QR labels* prints scannable labels for any roll.

Note: numbers that compare the story against "everything else" (find-cause rates, mass balance to date, earlier P&L
months) differ from the presentation, because there is more history here. That's expected.
