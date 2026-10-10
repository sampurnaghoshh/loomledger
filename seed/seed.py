"""Deterministic seed: builds Everest Textile Mills and the canonical Y-112 scenario.

Every row is derived from seed/scenario.py. Running it twice on a fresh schema produces identical data
(apart from database-generated ids and the time of the recall, which only happens in the demo).

Usage:
    python -m seed.seed                       # migrate --reset, then seed (DATABASE_URL)
    python -m seed.seed --anchor 2026-10-12   # move the demo day (numbers stay identical)
"""
from __future__ import annotations

import argparse
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import tuple_row

from db.migrate import database_url, migrate, reset_schema
from seed import scenario as S

TZ = ZoneInfo(S.TIMEZONE)
TOKEN_NAMESPACE = uuid.UUID("6f1c2a52-6a8e-4e0b-9a51-1c0de0f1ab12")


@dataclass
class Roll:
    code: str
    yarn: str
    family: str
    group: str                    # Y112 | V3B | V3A | B12 | AP | Y111
    reject: bool = False
    loom: str | None = None
    weave_start: datetime | None = None
    batch: "Batch | None" = None
    inspected_at: datetime | None = None
    defect: str | None = None
    ids: dict = field(default_factory=dict)


@dataclass
class Batch:
    code: str
    vat: str
    shift: str
    start: datetime
    family: str
    rolls: list[Roll]
    inspect_base: datetime | None = None
    inspected: bool = True

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=S.DYE_HOURS)


class Seeder:
    def __init__(self, conn: psycopg.Connection, anchor: date, qc_story_rejects: bool = True):
        self.c = conn
        self.anchor = anchor
        self.qc_story_rejects = qc_story_rejects   # False: R-1201..R-1203 wait for QC (rejected live / via the API)
        self.id: dict[str, dict[str, int]] = defaultdict(dict)
        self.rolls: dict[str, Roll] = {}
        self.batches: list[Batch] = []
        self.runs: list[tuple[str, str, str, datetime, datetime | None]] = []  # code, machine, shift, start, end

    # ------------------------------------------------------------------ helpers
    def at(self, day: int, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(self.anchor + timedelta(days=day), time(0), TZ) + timedelta(hours=hour, minutes=minute)

    def one(self, sql: str, params: tuple) -> int:
        with self.c.cursor(row_factory=tuple_row) as cur:      # independent of the caller's row factory
            return cur.execute(sql, params).fetchone()[0]

    def move(self, lot: str, src: str, dst: str, qty: D, kind: str, when: datetime, key: str, **refs) -> None:
        self.c.execute(
            """INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind,
                                       process_run_id, goods_receipt_id, dispatch_id, idempotency_key, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (self.id["lot"][lot], self.id["loc"][src], self.id["loc"][dst], qty, kind,
             refs.get("run"), refs.get("receipt"), refs.get("dispatch"), f"seed:{key}", when))

    @staticmethod
    def shift_of(t: datetime) -> str:
        return "A" if 8 <= t.hour < 20 else "B"

    # ------------------------------------------------------------------ masters
    def masters(self) -> None:
        for email, name, role in [
            ("owner@everest.test", "Rajesh Mehta", "owner"),
            ("store@everest.test", "Anil Kumar", "store"),
            ("floor@everest.test", "Suresh Patil", "floor_supervisor"),
            ("qc@everest.test", "Meena Iyer", "qc"),
            ("accounts@everest.test", "Farah Shaikh", "accounts"),
        ]:
            self.id["user"][role] = self.one(
                """INSERT INTO app_user (email, full_name, role, password_hash)
                   VALUES (%s, %s, %s, crypt('demo1234', gen_salt('bf'))) RETURNING id""", (email, name, role))

        for code, name, kind in [
            ("SUP-KAV", "Kaveri Yarn Traders", "supplier"),
            ("SUP-NAR", "Narmada Spinners", "supplier"),
            ("BUY-MER", "Meridian Apparels", "buyer"),
            ("BUY-CST", "Coastline Garments", "buyer"),
            ("BUY-BLB", "Bluebird Uniforms", "buyer"),
            ("BUY-SAF", "Saffron Home Linen", "buyer"),
        ]:
            self.id["party"][code] = self.one(
                "INSERT INTO party (code, name, kind) VALUES (%s, %s, %s) RETURNING id", (code, name, kind))

        products = [
            ("YRN-C40", "Cotton 40s Combed Yarn", "yarn", "kg", None, None, None, "40s Ne"),
            ("GRG-TWL", "Greige Twill", "greige", "m", S.GSM["twill"], S.FABRIC_WIDTH_M, None, None),
            ("GRG-POP", "Greige Poplin", "greige", "m", S.GSM["poplin"], S.FABRIC_WIDTH_M, None, None),
            ("FIN-TWL-NVY", "Navy Twill", "finished", "m", S.GSM["twill"], S.FABRIC_WIDTH_M, "Navy", None),
            ("FIN-POP-SKY", "Sky Blue Poplin", "finished", "m", S.GSM["poplin"], S.FABRIC_WIDTH_M, "Sky Blue", None),
        ]
        for code, name, kind, unit, gsm, width, colour, count in products:
            self.id["product"][code] = self.one(
                """INSERT INTO product (code, name, kind, uom, gsm, width_m, colour, yarn_count)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (code, name, kind, unit, gsm, width, colour, count))

        for code, name, kind in [
            ("SUPPLIERS", "Suppliers", "supplier"), ("CUSTOMERS", "Customers", "customer"),
            ("PRODUCTION", "Production", "production"), ("SCRAP", "Scrap", "scrap"),
            ("YARN-STORE", "Yarn Store", "internal"), ("GREIGE-STORE", "Greige Store", "internal"),
            ("FG-STORE", "Finished Goods Store", "internal"), ("REJECT-BAY", "Reject Bay", "internal"),
            ("QUARANTINE", "Quarantine Cage", "quarantine"),
        ]:
            self.id["loc"][code] = self.one(
                "INSERT INTO location (code, name, kind) VALUES (%s, %s, %s) RETURNING id", (code, name, kind))

        for code, name, start, end in [("A", "Day Shift A", time(8), time(20)), ("B", "Night Shift B", time(20), time(8))]:
            self.id["shift"][code] = self.one(
                "INSERT INTO shift (code, name, starts_at, ends_at) VALUES (%s, %s, %s, %s) RETURNING id",
                (code, name, start, end))

        for i in range(1, 7):
            self.id["machine"][f"LOOM-{i}"] = self.one(
                """INSERT INTO machine (code, name, stage, rate_per_hour, rated_output_per_hour)
                   VALUES (%s, %s, 'weaving', %s, %s) RETURNING id""",
                (f"LOOM-{i}", f"Loom {i}", S.LOOM_RATE_PER_H, S.ROLL_LENGTH_M / S.WEAVE_HOURS))
        for i in range(1, 4):
            self.id["machine"][f"VAT-{i}"] = self.one(
                """INSERT INTO machine (code, name, stage, rate_per_hour, rated_output_per_hour)
                   VALUES (%s, %s, 'dyeing', %s, %s) RETURNING id""",
                (f"VAT-{i}", f"Dye Vat {i}", S.VAT_RATE_PER_H, S.ROLL_LENGTH_M * S.DYE_BATCH_MAX / S.DYE_HOURS))
        self.id["machine"]["RF-1"] = self.one(
            """INSERT INTO machine (code, name, stage, rate_per_hour, rated_output_per_hour)
               VALUES ('RF-1', 'Ring Frame 1', 'spinning', 150, 12) RETURNING id""", ())

        workers = [(f"W-0{i}", f"Weaver {i}", "weaving", S.WEAVER_WAGE_PER_H, D("2.5")) for i in range(1, 7)]
        workers += [(f"D-0{i}", f"Dyer {i}", "dyeing", S.DYER_WAGE_PER_H, None) for i in range(1, 4)]
        workers += [("Q-01", "Kavya Rao", None, D("90"), None), ("Q-02", "Imran Khan", None, D("90"), None)]
        for code, name, skill, wage, piece in workers:
            self.id["worker"][code] = self.one(
                """INSERT INTO worker (code, full_name, skill, hourly_wage, piece_rate_per_m)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""", (code, name, skill, wage, piece))

        for family, finished in (("twill", "FIN-TWL-NVY"), ("poplin", "FIN-POP-SKY")):
            for stage, mpd in S.STAGE_CAPACITY[family].items():
                self.c.execute(
                    "INSERT INTO stage_capacity (product_id, stage, meters_per_day) VALUES (%s, %s, %s)",
                    (self.id["product"][finished], stage, mpd))

    # ------------------------------------------------------------------ yarn
    def receipts(self) -> None:
        for i, (lot, (_, kg, price, supplier, _)) in enumerate(S.YARN_LOTS.items()):
            when = self.at(-22 + i // 4, 10, 15 * (i % 4))      # all yarn is in before weaving starts on day -18
            grn = self.one(
                """INSERT INTO goods_receipt (code, supplier_id, received_at, vehicle_no, challan_no, received_by)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (f"GRN-{lot}", self.id["party"][supplier], when, f"KA-01-AB-{4100 + i}",
                 f"CH-{2600 + i}", self.id["user"]["store"]))
            self.id["lot"][lot] = self.one(
                """INSERT INTO lot (code, kind, product_id, qty, unit_cost, goods_receipt_id, created_at)
                   VALUES (%s, 'yarn', %s, %s, %s, %s, %s) RETURNING id""",
                (lot, self.id["product"]["YRN-C40"], kg, price, grn, when))
            self.move(lot, "SUPPLIERS", "YARN-STORE", kg, "receipt", when, f"grn:{lot}", receipt=grn)

    # ------------------------------------------------------------------ plan
    def plan(self) -> None:
        # Y-112: the story
        for code, (loom, custody, _) in S.Y112_ROLLS.items():
            self.rolls[code] = Roll(code, S.Y112, "twill", "Y112", reject=custody == "rejected", loom=loom)

        # Other lots, interleaved so each lot is spread across groups
        per_lot: dict[str, list[Roll]] = {}
        n = 1001
        for lot, (family, _, _, _, count) in S.YARN_LOTS.items():
            if lot == S.Y112:
                continue
            per_lot[lot] = []
            for _ in range(count):
                r = Roll(f"R-{n}", lot, family, "Y111" if lot == "Y-111" else "")
                per_lot[lot].append(r)
                self.rolls[r.code] = r
                n += 1

        reject_defects = iter(["hole", "uneven_weave", "oil_stain", "missing_pick"])
        for family, lots, reject_lots in (("twill", ["Y-101", "Y-102", "Y-103", "Y-104", "Y-105"], ["Y-102", "Y-104"]),
                                          ("poplin", ["Y-106", "Y-107", "Y-108", "Y-109", "Y-110"], ["Y-107", "Y-109"])):
            for lot in reject_lots:
                r = per_lot[lot][0]
                r.group, r.reject, r.defect = "AP", True, next(reject_defects)
            rest = [r for i in range(10) for lot in lots for r in [per_lot[lot][i]] if not r.group]
            sizes = {"V3B": 10, "V3A": 5, "B12": 10}
            for g, size in sizes.items():
                for r in rest[:size]:
                    r.group = g
                rest = rest[size:]
            for r in rest:
                r.group = "AP"

        # Weaving: Y-112 first on its fixed looms, everyone else on the least-loaded loom
        slots = {f"LOOM-{i}": [self.at(d, h) for d in range(-18, -6) for h in (8, 14)] for i in range(1, 7)}
        for code, roll in self.rolls.items():
            if roll.group == "Y112" and code != "R-1212":
                roll.weave_start = slots[roll.loom].pop(0)
        for roll in self.rolls.values():
            if roll.group != "Y112":
                loom = max(slots, key=lambda m: (len(slots[m]), -int(m[-1])))
                roll.loom, roll.weave_start = loom, slots[loom].pop(0)
        self.rolls["R-1212"].weave_start = self.at(0, 8)            # on Loom 5 right now

        # Dyeing: fixed story batches first, then groups into free vat slots
        y = self.rolls
        twill = lambda g: [r for r in self.rolls.values() if r.family == "twill" and r.group == g]  # noqa: E731
        v3b_twill, ap_twill = twill("V3B"), [r for r in twill("AP") if not r.reject]
        self.batches = [
            Batch("DB-01", "VAT-3", "B", self.at(-1, 20), "twill",
                  v3b_twill[:3] + [y["R-1201"], y["R-1202"], y["R-1203"]], inspect_base=self.at(0, 7, 30)),
            Batch("DB-02", "VAT-1", "A", self.at(-5, 8), "twill",
                  [y[c] for c in ("R-1204", "R-1205", "R-1206", "R-1207", "R-1208")] + ap_twill[:1]),
            Batch("DB-03", "VAT-2", "A", self.at(-1, 14), "twill",
                  [y[c] for c in ("R-1209", "R-1210", "R-1211")] + twill("Y111"), inspected=False),
        ]
        used = {(b.vat, b.start) for b in self.batches}
        taken = {r.code for b in self.batches for r in b.rolls}

        def free_slots(vats: list[str], shift: str):
            hours = (8, 14) if shift == "A" else (20, 26)
            for d in range(-6, 0):
                for h in hours:
                    for v in vats:
                        start = self.at(d, h)
                        if (v, start) not in used:
                            yield v, start

        n_batch = 4
        for g, vats, shift in (("V3B", ["VAT-3"], "B"), ("V3A", ["VAT-3"], "A"),
                               ("B12", ["VAT-1", "VAT-2"], "B"), ("AP", ["VAT-1", "VAT-2"], "A")):
            for family in ("twill", "poplin"):
                members = [r for r in self.rolls.values()
                           if r.group == g and r.family == family and r.code not in taken]
                k = math.ceil(len(members) / S.DYE_BATCH_MAX)
                chunks = [members[i::k] for i in range(k)]
                gen = free_slots(vats, shift)
                for chunk in chunks:
                    vat, start = next(gen)
                    used.add((vat, start))
                    self.batches.append(Batch(f"DB-{n_batch:02d}", vat, shift, start, family, chunk))
                    n_batch += 1

        for b in self.batches:
            for r in b.rolls:
                r.batch = b
        missing = [r.code for r in self.rolls.values() if r.batch is None and r.code != "R-1212"]
        assert not missing, f"rolls without a dye batch: {missing}"

    # ------------------------------------------------------------------ weaving
    def weave(self) -> None:
        for roll in sorted(self.rolls.values(), key=lambda r: (r.weave_start, r.code)):
            start = roll.weave_start
            end = None if roll.code == "R-1212" else start + timedelta(hours=S.WEAVE_HOURS)
            loom_no = roll.loom[-1]
            run_code = f"WV-{roll.code}"
            run = self.one(
                """INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at)
                   VALUES (%s, %s, 'weaving', %s, %s, %s, %s) RETURNING id""",
                (run_code, self.id["machine"][roll.loom], self.id["shift"][self.shift_of(start)],
                 self.id["worker"][f"W-0{loom_no}"], start, end))
            self.runs.append((run_code, roll.loom, self.shift_of(start), start, end))
            greige_product = "GRG-TWL" if roll.family == "twill" else "GRG-POP"
            greige = f"{roll.code}-G"
            self.id["lot"][greige] = self.one(
                """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, status, created_at)
                   VALUES (%s, 'greige', %s, %s, %s, 'weaving', %s, %s) RETURNING id""",
                (greige, self.id["product"][greige_product], S.ROLL_LENGTH_M, run,
                 "wip" if end is None else "active", start))
            issue = S.yarn_issue_kg(roll.family, roll.loom)
            self.move(roll.yarn, "YARN-STORE", "PRODUCTION", issue, "issue", start, f"issue:{run_code}", run=run)
            self.c.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                           (self.id["lot"][roll.yarn], self.id["lot"][greige], issue))
            if end is not None:
                self.move(roll.yarn, "PRODUCTION", "SCRAP", S.yarn_waste_kg(roll.family), "scrap", end,
                          f"waste:{run_code}", run=run)
                self.move(greige, "PRODUCTION", "GREIGE-STORE", S.ROLL_LENGTH_M, "production", end,
                          f"woven:{run_code}", run=run)
            roll.ids["run"] = run

    def busy_floor(self) -> None:
        """Act 1: looms weaving at demo "now" (scenario.BUSY_FLOOR) — open runs on WIP greige rolls, built
        exactly like a run started through POST /api/production/weaving-runs (and like R-1212 on Loom 5)."""
        start = self.at(0, S.BUSY_FLOOR_START_HOUR)
        n = max(int(code.removeprefix("R-")) for code in self.rolls) + 1
        for loom, yarn in S.BUSY_FLOOR.items():
            family = S.YARN_LOTS[yarn][0]
            code, run_code = f"R-{n}-G", f"WV-R-{n}"
            run = self.one(
                """INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at)
                   VALUES (%s, %s, 'weaving', %s, %s, %s) RETURNING id""",
                (run_code, self.id["machine"][loom], self.id["shift"][self.shift_of(start)],
                 self.id["worker"][f"W-0{loom[-1]}"], start))
            self.runs.append((run_code, loom, self.shift_of(start), start, None))
            self.id["lot"][code] = self.one(
                """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, status, created_at)
                   VALUES (%s, 'greige', %s, %s, %s, 'weaving', 'wip', %s) RETURNING id""",
                (code, self.id["product"]["GRG-TWL" if family == "twill" else "GRG-POP"], S.ROLL_LENGTH_M, run, start))
            issue = S.yarn_issue_kg(family, loom)
            self.move(yarn, "YARN-STORE", "PRODUCTION", issue, "issue", start, f"issue:{run_code}", run=run)
            self.c.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                           (self.id["lot"][yarn], self.id["lot"][code], issue))
            n += 1

    # ------------------------------------------------------------------ dyeing + QC
    def dye_and_inspect(self) -> None:
        dyer = {"VAT-1": "D-01", "VAT-2": "D-02", "VAT-3": "D-03"}
        for b in sorted(self.batches, key=lambda b: (b.start, b.vat)):
            run = self.one(
                """INSERT INTO process_run (code, machine_id, stage, shift_id, operator_id, started_at, ended_at, chemical_cost)
                   VALUES (%s, %s, 'dyeing', %s, %s, %s, %s, %s) RETURNING id""",
                (b.code, self.id["machine"][b.vat], self.id["shift"][b.shift], self.id["worker"][dyer[b.vat]],
                 b.start, b.end, S.DYE_CHEMICALS_PER_BATCH[b.family]))
            self.runs.append((b.code, b.vat, b.shift, b.start, b.end))
            finished_product = "FIN-TWL-NVY" if b.family == "twill" else "FIN-POP-SKY"
            for r in b.rolls:
                greige = f"{r.code}-G"
                self.move(greige, "GREIGE-STORE", "PRODUCTION", S.ROLL_LENGTH_M, "consumption", b.start,
                          f"dye-in:{b.code}:{r.code}", run=run)
                self.c.execute("UPDATE lot SET status = 'consumed' WHERE id = %s", (self.id["lot"][greige],))
                self.id["lot"][r.code] = self.one(
                    """INSERT INTO lot (code, kind, product_id, qty, produced_by_run_id, produced_by_stage, created_at)
                       VALUES (%s, 'finished', %s, %s, %s, 'dyeing', %s) RETURNING id""",
                    (r.code, self.id["product"][finished_product], S.ROLL_LENGTH_M, run, b.end))
                self.c.execute("INSERT INTO lot_lineage (parent_lot_id, child_lot_id, qty_consumed) VALUES (%s, %s, %s)",
                               (self.id["lot"][greige], self.id["lot"][r.code], S.ROLL_LENGTH_M))
                self.move(r.code, "PRODUCTION", "FG-STORE", S.ROLL_LENGTH_M, "production", b.end,
                          f"dyed:{b.code}:{r.code}", run=run)

            if not b.inspected:
                continue
            base = b.inspect_base or b.end + timedelta(minutes=30)
            inspector = self.id["worker"]["Q-01" if int(b.code[-2:]) % 2 else "Q-02"]
            for i, r in enumerate(sorted(b.rolls, key=lambda r: (r.reject, r.code))):
                if r.group == "Y112" and r.reject and not self.qc_story_rejects:
                    continue
                r.inspected_at = base + timedelta(minutes=5 * i)
                defect = S.DEFECT if r.group == "Y112" and r.reject else r.defect
                self.c.execute(
                    """INSERT INTO qc_inspection (lot_id, inspector_id, inspected_at, result, defect_type, defect_meters)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (self.id["lot"][r.code], inspector, r.inspected_at,
                     "reject" if r.reject else "pass", defect if r.reject else None,
                     S.ROLL_LENGTH_M if r.reject else None))
                if r.reject:
                    self.move(r.code, "FG-STORE", "REJECT-BAY", S.ROLL_LENGTH_M, "transfer", r.inspected_at,
                              f"reject:{r.code}")

    # ------------------------------------------------------------------ orders, reservations, dispatch, money
    def orders(self) -> None:
        finished = {"twill": "FIN-TWL-NVY", "poplin": "FIN-POP-SKY"}
        status = {"SO-0398": "dispatched", "SO-0405": "in_production",
                  "SO-0412": "partially_dispatched", "SO-0419": "in_production"}
        line: dict[str, int] = {}
        for o in S.ORDERS:
            oid = self.one(
                """INSERT INTO sales_order (code, buyer_id, order_date, promised_date, status)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (o.code, self.id["party"][o.buyer], self.anchor + timedelta(days=o.order_offset),
                 self.anchor + timedelta(days=o.promise_offset), status[o.code]))
            self.id["order"][o.code] = oid
            line[o.code] = self.one(
                """INSERT INTO order_line (order_id, product_id, qty_m, unit_price)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (oid, self.id["product"][finished[o.family]], o.qty_m, S.PRICE_PER_M[o.family]))
            self.c.execute(
                """INSERT INTO order_event (order_id, kind, message, visible_to_buyer, created_at)
                   VALUES (%s, 'confirmed', %s, true, %s)""",
                (oid, f"Order confirmed: {o.qty_m:,} m. Promised dispatch "
                      f"{(self.anchor + timedelta(days=o.promise_offset)).strftime('%d %b %Y')}.",
                 self.at(o.order_offset, 11)))

        def reserve(code: str, order: str, when: datetime) -> None:
            self.c.execute("INSERT INTO reservation (lot_id, order_line_id, reserved_at) VALUES (%s, %s, %s)",
                           (self.id["lot"][code], line[order], when))

        # Y-112 rolls: reserved as they were planned
        for code, (_, custody, order) in S.Y112_ROLLS.items():
            lot_code = code if custody != "wip" else f"{code}-G"
            reserve(lot_code, order, self.rolls[code].weave_start)

        passed = lambda fam: sorted((r for r in self.rolls.values()  # noqa: E731
                                     if r.family == fam and r.group not in ("Y112", "Y111")
                                     and not r.reject and r.inspected_at),
                                    key=lambda r: (r.inspected_at, r.code))
        twill_ok, poplin_ok = passed("twill"), passed("poplin")
        alloc = {"SO-0412": twill_ok[:20], "SO-0419": twill_ok[20:30],
                 "SO-0398": poplin_ok[:30], "SO-0405": poplin_ok[30:48]}
        for order, rolls in alloc.items():
            for r in rolls:
                reserve(r.code, order, r.inspected_at)

        # Dispatches
        dispatches = [
            ("DSP-0398-1", "SO-0398", self.at(-2, 11), [r.code for r in alloc["SO-0398"]]),
            ("DSP-0412-1", "SO-0412", self.at(-1, 16),
             ["R-1204", "R-1205"] + [r.code for r in alloc["SO-0412"][:10]]),
        ]
        for code, order, when, lots in dispatches:
            late = [c for c in lots if self.rolls[c].inspected_at is None or self.rolls[c].inspected_at >= when]
            assert not late, f"{code}: rolls not inspected before dispatch: {late}"
            # these historical shipments mix dye batches; Shade Guard (008) needs the approval on record
            did = self.one(
                """INSERT INTO dispatch (code, order_id, vehicle_no, dispatched_at, shade_override_reason)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (code, self.id["order"][order], "KA-05-TR-7781", when,
                 "Buyer approved mixed dye lots for this shipment."))
            for c in lots:
                self.c.execute("INSERT INTO dispatch_line (dispatch_id, lot_id) VALUES (%s, %s)",
                               (did, self.id["lot"][c]))
                self.move(c, "FG-STORE", "CUSTOMERS", S.ROLL_LENGTH_M, "dispatch", when, f"ship:{code}:{c}",
                          dispatch=did)
                self.c.execute("UPDATE lot SET status = 'dispatched' WHERE id = %s", (self.id["lot"][c],))
            family = next(o.family for o in S.ORDERS if o.code == order)
            amount = S.PRICE_PER_M[family] * S.ROLL_LENGTH_M * len(lots)
            inv = self.one(
                """INSERT INTO invoice (code, order_id, dispatch_id, amount, issued_at)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (code.replace("DSP", "INV"), self.id["order"][order], did, amount, when))
            if order == "SO-0398":
                self.c.execute(
                    "INSERT INTO payment (invoice_id, amount, paid_at, method) VALUES (%s, %s, %s, 'bank_transfer')",
                    (inv, amount, self.at(-1, 12)))
            self.c.execute(
                """INSERT INTO order_event (order_id, kind, message, visible_to_buyer, created_at)
                   VALUES (%s, 'dispatched', %s, true, %s)""",
                (self.id["order"][order],
                 f"Dispatched {len(lots)} rolls ({len(lots) * int(S.ROLL_LENGTH_M):,} m) on vehicle KA-05-TR-7781.",
                 when))

    # ------------------------------------------------------------------ floor, people, portal
    def floor_and_people(self) -> None:
        by_machine: dict[str, list[tuple[datetime, datetime | None]]] = defaultdict(list)
        for _, machine, _, start, end in self.runs:
            by_machine[machine].append((start, end))
        by_machine["LOOM-4"].append(("breakdown", self.at(-10, 20), self.at(-10, 23)))  # type: ignore[arg-type]

        for machine in self.id["machine"]:
            entries = sorted(by_machine.get(machine, []), key=lambda e: e[-2] if len(e) == 3 else e[0])
            last_end = self.at(-20, 6)
            open_state = False
            for e in entries:
                state, start, end = ("breakdown", e[1], e[2]) if len(e) == 3 else ("running", e[0], e[1])
                self.c.execute(
                    """INSERT INTO machine_state_log (machine_id, state, reason, started_at, ended_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (self.id["machine"][machine], state,
                     "Warp beam bearing failure" if state == "breakdown" else None, start, end))
                if end is None:
                    open_state = True
                else:
                    last_end = max(last_end, end)
            if not open_state:
                self.c.execute(
                    "INSERT INTO machine_state_log (machine_id, state, started_at) VALUES (%s, 'idle', %s)",
                    (self.id["machine"][machine], last_end))

        operators = {"LOOM": "W-0", "VAT": "D-0"}
        for code, machine, shift, start, _ in self.runs:
            prefix = machine.split("-")[0]
            worker = f"{operators[prefix]}{machine[-1]}"
            self.c.execute(
                """INSERT INTO attendance (worker_id, work_date, shift_id, status)
                   VALUES (%s, %s, %s, 'present') ON CONFLICT DO NOTHING""",
                (self.id["worker"][worker], start.date(), self.id["shift"][shift]))

        # Workforce register: every working day on the usual shift (scenario.expected_register); the run-implied
        # rows above stay. An exception must not contradict a run (absent while operating a loom).
        for code, days in S.expected_register(self.anchor).items():
            for day, (status, shift) in days.items():
                if status != "present":
                    clash = self.c.execute("SELECT 1 FROM attendance WHERE worker_id = %s AND work_date = %s",
                                           (self.id["worker"][code], day)).fetchone()
                    assert clash is None, f"attendance exception {code} {day} {status} falls on a day {code} ran a machine"
                self.c.execute(
                    """INSERT INTO attendance (worker_id, work_date, shift_id, status)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (self.id["worker"][code], day, self.id["shift"][shift], status))

        for o in S.ORDERS:
            self.c.execute(
                "INSERT INTO buyer_link (token, order_id, expires_at) VALUES (%s, %s, %s)",
                (uuid.uuid5(TOKEN_NAMESPACE, o.code), self.id["order"][o.code], self.at(60, 0)))

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.masters()
        self.receipts()
        self.plan()
        self.weave()
        self.busy_floor()
        self.dye_and_inspect()
        self.orders()
        self.floor_and_people()


def buyer_token(order_code: str) -> uuid.UUID:
    """Demo tokens are deterministic so the demo URL never changes. Production links use gen_random_uuid()."""
    return uuid.uuid5(TOKEN_NAMESPACE, order_code)


def seed(conn: psycopg.Connection, anchor: date = S.ANCHOR_DATE, *, qc_story_rejects: bool = True) -> None:
    """qc_story_rejects=False leaves the three story rolls (R-1201..R-1203) awaiting QC instead of rejected."""
    conn.commit()   # never nest inside a caller's open transaction: the seed is all-or-nothing on its own
    with conn.transaction():
        Seeder(conn, anchor, qc_story_rejects).run()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", type=date.fromisoformat, default=S.ANCHOR_DATE,
                        help="demo day, YYYY-MM-DD (default: %(default)s)")
    args = parser.parse_args()
    if args.anchor.isoweekday() == 7:
        parser.error(f"{args.anchor} is a Sunday and the mill works Monday-Saturday; "
                     f"use the Saturday before ({args.anchor - timedelta(days=1)})")
    with psycopg.connect(database_url()) as conn:
        reset_schema(conn)
        migrate(conn)
        seed(conn, args.anchor)
    print(f"seeded Everest Textile Mills, demo day {args.anchor}")
    for o in S.ORDERS:
        print(f"  buyer link {o.code}: /track/{buyer_token(o.code)}")


if __name__ == "__main__":
    main()
