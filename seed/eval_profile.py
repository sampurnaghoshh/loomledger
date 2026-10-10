"""Seed profile `eval`: the demo story + ~300 extra rolls of realistic history for evaluators to explore.

    python -m seed.seed --profile eval        (or: scripts/reset_demo.ps1 -Eval  →  database loomledger_eval)

Everything here happens BEFORE the story (days -92 … -31 relative to the demo day), so nothing in the story
window moves: the story rows are inserted first, exactly as in the demo profile, and this history is added after
them (ids differ from the demo database only for these extra rows). The history goes through the same doors as
the story: goods receipts, weaving runs issuing yarn from the store, dyeing runs consuming greige, QC, reservations,
dispatches (shade guard, QC guard), invoices and payments (overpayment guard) — every movement through stock_move.

Deterministic: one fixed random seed. Story numbers that compare against "everything else" (find-cause rates,
mass balance to date, P&L for earlier months, availability) naturally differ in this database; the DEMO profile
is untouched and stays byte-identical (tests/test_eval_profile.py).
"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal as D

from seed import scenario as S

RANDOM_SEED = 20261010
FIRST_DAY, LAST_DAY = -92, -31              # the whole eval history lives in this window (before the 30-day register)
YARN_LOTS = 12                              # Y-301 … Y-312
ROLLS_PER_LOT = 25                          # 300 rolls: R-2001 … R-2300
GREIGE_ONLY = 18                            # woven, never dyed: still in the greige store
NOT_INSPECTED_BATCHES = 3                   # dyed, awaiting QC
DEFECTS = ["colour_mismatch", "missing_pick", "oil_stain", "hole", "uneven_weave", "other"]

SUPPLIERS = [("SUP-GUJ", "Gujarat Cotton Mills"), ("SUP-TIR", "Tiruppur Yarn House")]
BUYERS = [("BUY-ARV", "Aravind Exports"), ("BUY-LTX", "Lotus Textiles"), ("BUY-PRM", "Prism Fashions"),
          ("BUY-KSR", "Kesar Uniforms"), ("BUY-NIL", "Nila Home Furnishings"), ("BUY-TRD", "Trident Workwear"),
          ("BUY-SUN", "Sunrise Garments"), ("BUY-VRD", "Verdant Apparel"), ("BUY-MNS", "Monsoon Linens"),
          ("BUY-GLD", "Golden Thread Co."), ("BUY-IND", "Indigo Street")]
ORDER_STATUSES = (["dispatched"] * 20 + ["partially_dispatched"] * 10 + ["in_production"] * 15
                  + ["confirmed"] * 10 + ["cancelled"] * 5)
TOKEN_NAMESPACE = uuid.UUID("0e7a1b52-7d3c-4f1e-9a0b-ee11ab5e0001")


@dataclass
class EvalRoll:
    code: str
    yarn: str
    family: str
    loom: str = ""
    start: datetime | None = None
    end: datetime | None = None
    batch: str | None = None
    dyed_at: datetime | None = None
    qc: list[tuple[datetime, str, str | None]] = field(default_factory=list)   # (when, result, defect)

    @property
    def passed_at(self) -> datetime | None:
        return self.qc[-1][0] if self.qc and self.qc[-1][1] == "pass" else None


def add_history(s) -> None:
    """`s` is the demo Seeder after the story is in (before floor_and_people, so these runs get machine-state
    rows and run-implied attendance exactly like the story's)."""
    rnd = random.Random(RANDOM_SEED)
    day = lambda d, h=0, m=0: s.at(d, h, m)  # noqa: E731

    # ---------------- parties
    for code, name in SUPPLIERS:
        s.id["party"][code] = s.one("INSERT INTO party (code, name, kind) VALUES (%s, %s, 'supplier') RETURNING id",
                                    (code, name))
    for code, name in BUYERS:
        s.id["party"][code] = s.one("INSERT INTO party (code, name, kind, phone) VALUES (%s, %s, 'buyer', %s) RETURNING id",
                                    (code, name, f"+91 98{rnd.randint(10000000, 99999999)}"))
    suppliers = ["SUP-KAV", "SUP-NAR"] + [c for c, _ in SUPPLIERS]
    buyers = [o.buyer for o in S.ORDERS] + [c for c, _ in BUYERS]

    # ---------------- yarn: one lot per 25 rolls, received every ~4 days
    rolls: list[EvalRoll] = []
    lot_kg: dict[str, D] = {}
    for i in range(YARN_LOTS):
        lot, family = f"Y-{301 + i}", ("twill", "poplin")[i % 2]
        lot_rolls = [EvalRoll(f"R-{2001 + i * ROLLS_PER_LOT + k}", lot, family) for k in range(ROLLS_PER_LOT)]
        rolls += lot_rolls
        lot_kg[lot] = D(0)          # filled once looms are known (the leaky loom issues more)

    # ---------------- weaving: lot i can start the day after it is received; 3 slots a day on 6 looms
    slots = {f"LOOM-{n}": [] for n in range(1, 7)}
    taken: set[tuple[str, datetime]] = set()
    received = {f"Y-{301 + i}": day(FIRST_DAY + 4 * i, 10, 30) for i in range(YARN_LOTS)}
    for r in rolls:
        earliest = received[r.yarn] + timedelta(hours=18)
        best = None
        d = (earliest.date() - s.anchor).days
        while best is None:
            for h in (8, 14, 20):
                t = day(d, h)
                if t < earliest:
                    continue
                free = [lm for lm in slots if (lm, t) not in taken]
                if free:
                    best = (rnd.choice(free), t)
                    break
            d += 1
        r.loom, r.start = best
        r.end = r.start + timedelta(hours=S.WEAVE_HOURS)
        taken.add(best)
        lot_kg[r.yarn] += S.yarn_issue_kg(r.family, r.loom)
    assert max(r.end for r in rolls) < day(LAST_DAY - 12), "eval weaving runs too late"

    for i, (lot, need) in enumerate(lot_kg.items()):
        kg = D(math.ceil(need)) + rnd.randint(4, 30)                       # leftover yarn stays in the store
        price = D(rnd.randint(248, 272))
        supplier = suppliers[i % len(suppliers)]
        grn = s.one("""INSERT INTO goods_receipt (code, supplier_id, received_at, vehicle_no, challan_no, received_by)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                    (f"GRN-{lot}", s.id["party"][supplier], received[lot], f"GJ-05-CT-{3100 + i}", f"CH-{3300 + i}",
                     s.id["user"]["store"]))
        s.id["lot"][lot] = s.one("""INSERT INTO lot (code, kind, product_id, qty, unit_cost, goods_receipt_id, created_at)
                                    VALUES (%s, 'yarn', %s, %s, %s, %s, %s) RETURNING id""",
                                 (lot, s.id["product"]["YRN-C40"], kg, price, grn, received[lot]))
        s.move(lot, "SUPPLIERS", "YARN-STORE", kg, "receipt", received[lot], f"eval:grn:{lot}", receipt=grn)
        s.id["grn"][lot] = grn
        lot_kg[lot] = kg * price                                           # now: the bill

    for r in sorted(rolls, key=lambda r: (r.start, r.loom)):
        run_code = f"WV-{r.code}"
        run = s.one("""INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at)
                       VALUES (%s, %s, 'weaving', %s, %s, %s, %s) RETURNING id""",
                    (run_code, s.id["machine"][r.loom], s.id["shift"][s.shift_of(r.start)],
                     s.id["worker"][f"W-0{r.loom[-1]}"], r.start, r.end))
        s.runs.append((run_code, r.loom, s.shift_of(r.start), r.start, r.end))
        greige = f"{r.code}-G"
        s.id["lot"][greige] = s.one(
            """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, created_at)
               VALUES (%s, 'greige', %s, %s, %s, 'weaving', %s) RETURNING id""",
            (greige, s.id["product"]["GRG-TWL" if r.family == "twill" else "GRG-POP"], S.ROLL_LENGTH_M, run, r.start))
        issue = S.yarn_issue_kg(r.family, r.loom)
        s.move(r.yarn, "YARN-STORE", "PRODUCTION", issue, "issue", r.start, f"eval:issue:{run_code}", run=run)
        s.c.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                    (s.id["lot"][r.yarn], s.id["lot"][greige], issue))
        s.move(r.yarn, "PRODUCTION", "SCRAP", S.yarn_waste_kg(r.family), "scrap", r.end, f"eval:waste:{run_code}", run=run)
        s.move(greige, "PRODUCTION", "GREIGE-STORE", S.ROLL_LENGTH_M, "production", r.end, f"eval:woven:{run_code}", run=run)

    # ---------------- dyeing: batches of up to 6 rolls of one family, earliest free vat slot after the last weave
    to_dye = sorted(rolls, key=lambda r: (r.end, r.code))
    greige_only = set(rnd.sample(range(len(to_dye)), GREIGE_ONLY))
    queue = {"twill": [], "poplin": []}
    for i, r in enumerate(to_dye):
        if i not in greige_only:
            queue[r.family].append(r)
    batches: list[tuple[str, list[EvalRoll]]] = []
    for family, members in queue.items():
        for i in range(0, len(members), S.DYE_BATCH_MAX):
            batches.append((family, members[i:i + S.DYE_BATCH_MAX]))
    vat_taken: set[tuple[str, datetime]] = set()
    dyer = {"VAT-1": "D-01", "VAT-2": "D-02", "VAT-3": "D-03"}
    finished_product = {"twill": "FIN-TWL-NVY", "poplin": "FIN-POP-SKY"}
    planned = []
    for family, members in batches:
        earliest = max(r.end for r in members) + timedelta(hours=2)
        d, slot = (earliest.date() - s.anchor).days, None
        while slot is None:
            for h in (8, 14, 20, 26):
                t = day(d, h)
                free = [v for v in dyer if (v, t) not in vat_taken]
                if t >= earliest and free:
                    slot = (rnd.choice(free), t)
                    break
            d += 1
        vat_taken.add(slot)
        planned.append((slot[1], slot[0], family, members))
    planned.sort(key=lambda p: (p[0], p[1]))
    uninspected = {id(p[3]) for p in planned[-NOT_INSPECTED_BATCHES:]}
    for n, (start, vat, family, members) in enumerate(planned):
        code, end, shift = f"DB-{101 + n}", start + timedelta(hours=S.DYE_HOURS), s.shift_of(start)
        run = s.one("""INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at, chemical_cost)
                       VALUES (%s, %s, 'dyeing', %s, %s, %s, %s, %s) RETURNING id""",
                    (code, s.id["machine"][vat], s.id["shift"][shift], s.id["worker"][dyer[vat]], start, end,
                     S.DYE_CHEMICALS_PER_BATCH[family]))
        s.runs.append((code, vat, shift, start, end))
        for r in members:
            greige = f"{r.code}-G"
            s.move(greige, "GREIGE-STORE", "PRODUCTION", S.ROLL_LENGTH_M, "consumption", start,
                   f"eval:dye-in:{code}:{r.code}", run=run)
            s.c.execute("UPDATE lot SET status = 'consumed' WHERE id = %s", (s.id["lot"][greige],))
            s.id["lot"][r.code] = s.one(
                """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, created_at)
                   VALUES (%s, 'finished', %s, %s, %s, 'dyeing', %s) RETURNING id""",
                (r.code, s.id["product"][finished_product[family]], S.ROLL_LENGTH_M, run, end))
            s.c.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                        (s.id["lot"][greige], s.id["lot"][r.code], S.ROLL_LENGTH_M))
            s.move(r.code, "PRODUCTION", "FG-STORE", S.ROLL_LENGTH_M, "production", end, f"eval:dyed:{code}:{r.code}", run=run)
            r.batch, r.dyed_at = code, end

        # ---------------- QC: ~6 % reject, ~6 % rework (most reworked rolls pass on re-inspection)
        if id(members) in uninspected:
            continue
        for i, r in enumerate(members):
            when = end + timedelta(minutes=30 + 6 * i)
            roll_dice = rnd.random()
            if roll_dice < 0.06:
                r.qc.append((when, "reject", rnd.choice(DEFECTS)))
            elif roll_dice < 0.12:
                r.qc.append((when, "rework", rnd.choice(DEFECTS)))
                if rnd.random() < 0.7:
                    r.qc.append((when + timedelta(hours=20), "pass", None))
            else:
                r.qc.append((when, "pass", None))
            for at, result, defect in r.qc:
                s.c.execute(
                    """INSERT INTO qc_inspection (lot_id, inspector_id, inspected_at, result, defect_type, defect_meters)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (s.id["lot"][r.code], s.id["worker"][rnd.choice(["Q-01", "Q-02"])], at, result, defect,
                     None if result == "pass" else (S.ROLL_LENGTH_M if result == "reject" else D(rnd.randint(2, 12)))))
                if result == "reject":
                    s.move(r.code, "FG-STORE", "REJECT-BAY", S.ROLL_LENGTH_M, "transfer", at, f"eval:reject:{r.code}")

    # ---------------- orders: 60 across every status, each with a buyer link
    passed = {fam: sorted((r for r in rolls if r.family == fam and r.passed_at), key=lambda r: (r.passed_at, r.code))
              for fam in ("twill", "poplin")}
    statuses = ORDER_STATUSES[:]
    rnd.shuffle(statuses)
    orders = []
    for n, status in enumerate(statuses):
        family = ("twill", "poplin")[n % 2]
        ordered = day(FIRST_DAY + 2 + (n * 3) // 4, 11)          # days -90 … -46: before the rolls they get
        orders.append((f"SO-{301 + n:04d}", rnd.choice(buyers), family, status, ordered))

    for code, buyer, family, status, ordered in orders:
        wants = {"dispatched": rnd.randint(3, 5), "partially_dispatched": rnd.randint(4, 6),
                 "in_production": rnd.randint(2, 4)}.get(status, 0)
        pool = passed[family]
        reserved = [pool.pop(0) for _ in range(min(wants, len(pool)))]
        n_rolls = len(reserved) + rnd.randint(1, 4) if status != "dispatched" else len(reserved)
        n_rolls = max(n_rolls, 2)
        promised = (ordered + timedelta(days=rnd.randint(14, 28))).date()
        oid = s.one("""INSERT INTO sales_order (code, buyer_id, order_date, promised_date, status)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (code, s.id["party"][buyer], ordered.date(), promised,
                     status if (reserved or status in ("confirmed", "cancelled")) else "confirmed"))
        line = s.one("""INSERT INTO order_line (order_id, product_id, qty_m, unit_price) VALUES (%s, %s, %s, %s) RETURNING id""",
                     (oid, s.id["product"][finished_product[family]], S.ROLL_LENGTH_M * n_rolls, S.PRICE_PER_M[family]))
        s.c.execute("""INSERT INTO order_event (order_id, kind, message, visible_to_buyer, created_at)
                       VALUES (%s, 'confirmed', %s, true, %s)""",
                    (oid, f"Order confirmed: {int(S.ROLL_LENGTH_M * n_rolls):,} m. Promised dispatch {promised:%d %b %Y}.", ordered))
        s.c.execute("INSERT INTO buyer_link (token, order_id, expires_at) VALUES (%s, %s, %s)",
                    (uuid.uuid5(TOKEN_NAMESPACE, code), oid, s.at(60, 0)))
        for r in reserved:
            s.c.execute("INSERT INTO reservation (lot_id, order_line_id, reserved_at) VALUES (%s, %s, %s)",
                        (s.id["lot"][r.code], line, max(r.passed_at, ordered)))

        ship = reserved if status == "dispatched" else reserved[:len(reserved) // 2] if status == "partially_dispatched" else []
        if not ship:
            continue
        when = max(max(r.passed_at for r in ship), ordered) + timedelta(days=rnd.randint(1, 4), hours=rnd.randint(1, 6))
        when = min(when, day(LAST_DAY - 3, 16))
        assert all(r.passed_at < when for r in ship), f"{code}: dispatch before QC pass"
        mixed = len({r.batch for r in ship}) > 1
        did = s.one("""INSERT INTO dispatch (code, order_id, vehicle_no, dispatched_at, shade_override_reason)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (f"DSP-{code[3:]}-1", oid, f"MH-04-TR-{rnd.randint(1000, 9999)}", when,
                     "Buyer approved mixed dye lots for this shipment." if mixed else None))
        for r in ship:
            s.c.execute("INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)", (did, s.id["lot"][r.code]))
            s.move(r.code, "FG-STORE", "CUSTOMERS", S.ROLL_LENGTH_M, "dispatch", when, f"eval:ship:{code}:{r.code}", dispatch=did)
            s.c.execute("UPDATE lot SET status = 'dispatched' WHERE id = %s", (s.id["lot"][r.code],))
        amount = S.PRICE_PER_M[family] * S.ROLL_LENGTH_M * len(ship)
        inv = s.one("""INSERT INTO invoice (code, order_id, dispatch_id, amount, issued_at) VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (f"INV-{code[3:]}-1", oid, did, amount, when))
        s.c.execute("""INSERT INTO order_event (order_id, kind, message, visible_to_buyer, created_at)
                       VALUES (%s, 'dispatched', %s, true, %s)""",
                    (oid, f"Dispatched {len(ship)} rolls ({len(ship) * int(S.ROLL_LENGTH_M):,} m).", when))
        # buyer payments: most pay in full, some in part, some not yet (never above the invoice: LL009)
        dice = rnd.random()
        paid = amount if dice < 0.6 else (amount * D(rnd.choice([25, 40, 50])) / 100).quantize(D("1")) if dice < 0.85 else None
        if paid:
            s.c.execute("""INSERT INTO payment (invoice_id, amount, paid_at, method, idempotency_key)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (inv, paid, min(when + timedelta(days=rnd.randint(2, 9)), day(LAST_DAY, 12)),
                         rnd.choice(["bank_transfer", "upi", "cheque"]), f"eval:pay:{code}"))

    # ---------------- supplier payments: most yarn bills paid, a few still open
    for i, (lot, bill) in enumerate(lot_kg.items()):
        if i % 4 == 3:
            continue
        amount = bill if i % 3 else (bill / 2).quantize(D("1"))
        s.c.execute("""INSERT INTO supplier_payment (goods_receipt_id, amount, paid_at, method, idempotency_key)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (s.id["grn"][lot], amount, received[lot] + timedelta(days=7), "bank_transfer", f"eval:bill:{lot}"))

    # ---------------- QC staff on the days they inspected (machine operators come from the runs)
    for r in rolls:
        for at, _, _ in r.qc:
            q_shift = s.shift_of(at)
            s.c.execute("""INSERT INTO attendance (worker_id, work_date, shift_id, status) VALUES (%s, %s, %s, 'present')
                           ON CONFLICT DO NOTHING""",
                        (s.id["worker"]["Q-01" if q_shift == "A" else "Q-02"], at.date(), s.id["shift"][q_shift]))
