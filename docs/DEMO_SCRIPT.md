# LoomLedger · demo script (one line per click)

Two people: **P** = presenter (talks, holds the scanner phone), **D** = driver (laptop, logged in as owner).
Owner phone face up on the table, **armed** on `/alerts`. Setup and recovery: [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).
**Read every number from the screen — never from memory, never typed.**

## Opening (20 s)
- **P:** "A factory is two things: a ledger and a family tree. Everything you'll see is derived from those two, inside PostgreSQL."

## Act 1 · A normal day (60 s)
- **D:** Floor Board. **P:** "Saturday at Everest Textile Mills — these looms are weaving, each on its own roll." *(read *Machines running*)*
- **P:** "The grey bars say the rolls are woven to plan and due off the loom — this is the floor exactly as the mill left it on Saturday. We don't fake the clock."
- **D:** Loom 4 → Change state → Breakdown → reason → Save. **P:** "A loom breaks down…"
- **P** *(points at the owner phone, now amber)*: "…and the owner's phone knows instantly — pushed by the database, no refresh, no SMS service."
- **D** *(optional)*: Inventory → a past time → View. **P:** "Stock is never stored: this is the ledger replayed to that moment."

## Act 2 · Something's wrong (60 s)
- **D:** Quality → **Find cause** on the banner. **P:** "QC rejected rolls for colour mismatch. Everyone blames the dye vat…"
- **P** *(reads the headline)*: "LoomLedger walks every roll's family tree and compares defect rates: the yarn lot is the cause — read the rate through it versus everywhere else."
- **P** *(points at 'why these are not the cause')*: "The vat and the night shift look guilty but are coincidental — good rolls went through them too."

## Act 3 · Contain it (90 s)
- **P** *(scans the R-1204 label with the scanner phone)*: "This roll is already at the buyer — its passport shows where it came from."
- **D:** Recall \<yarn lot\> → Apply recall → reason → Quarantine everything. **P:** "One click, one transaction: quarantine everything made from that lot."
- **P** *(owner phone turns red, three beeps)*: "And the owner's phone: rolls affected, buyers holding goods, orders, the delay, the total exposure — and what to do next."
- **P** *(refreshes the passport)*: "Same roll, same QR: now quarantined, with the recall code and its new promised date."
- **D:** Recall → Issue \<yarn lot\> to \<loom\>. **P:** "Someone tries to use that yarn anyway… the database refuses."
- **D:** Window 3 → Enter. **P:** "Not the UI — PostgreSQL itself. Even raw SQL can't do it."

## Act 4 · Business impact (60 s)
- **D:** Recall → scroll. **P** *(reads)*: "Remake divided by the weaving bottleneck, rounded up — that's the delay in working days. And the total exposure, split into what's already lost, what the recall exposes, and what we can claim back from the supplier."
- **D:** Orders. **P:** "Both orders re-promised automatically — and one is now short of yarn, because quarantined yarn no longer counts."
- **P** *(buyer tab on the phone, refresh)*: "The buyer sees the new date and a message about the rolls they already hold — no email, no call."

## Close (45 s)
- **D:** Month-end → mass balance. **P** *(reads)*: "Every kilo of yarn accounted for — except a small gap, and the system says which loom it's on."
- **D:** True cost per roll. **P:** "The real cost of every roll: yarn, machine, labour, chemicals."
- **D:** Profit & loss. **P:** "It's a loss this month, and we show it honestly: a month of wages is booked while only some shipments are invoiced — and the recall exposure sits beside it as contingent, not buried."
- **D:** Workforce → Wages. **P:** "Who worked which shift — and that's what feeds the wage line."
- **P** *(points at the Yarn low banner)*: "And after the quarantine, usable yarn is below the reorder level — it tells the store to buy."
- **P:** "The factory knew it had a defect. LoomLedger knows where it came from, what it touched, what it cost, and what to do next."

## If asked
- *"Can someone bypass it?"* → Admin → Validation log: every refused attempt, who, when, why. Roles & permissions: the table the API checks.
- *"Is this all fake data?"* → the evaluator playground (`docs/EVALUATOR_GUIDE.md`): the same story inside ~300 more rolls of history.
- *"Tests?"* → the golden test + ledger invariants + API tests, and a smoke run of the whole story over HTTP (39 checks).
