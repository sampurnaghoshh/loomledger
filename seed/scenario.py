"""The canonical Y-112 scenario — the single source of truth.

The seed builds the database from these constants, the golden test asserts against them,
and the demo script quotes them. If a number changes, it changes HERE and nowhere else.

The expected money figures are computed below with plain Python arithmetic, independently of
the SQL cost roll-up, so the golden test is a genuine cross-check of the database logic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal as D

# ---------------------------------------------------------------------------
# Demo clock. Everything is placed relative to this day (09:00–10:00 is "now" in the story).
# ---------------------------------------------------------------------------
ANCHOR_DATE = date(2026, 10, 10)          # a Saturday
TIMEZONE = "Asia/Kolkata"
RECALL_APPLIED_AT = time(9, 45)           # when the recall is applied in the story (mock export pins it here)

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
ROLL_LENGTH_M = D("50")
FABRIC_WIDTH_M = D("1.5")
GSM = {"twill": 200, "poplin": 120}
YARN_WASTE_RATIO = D("0.04")              # 4 % recorded loom waste
LEAKY_MACHINE = "LOOM-3"                  # issues more yarn than it can account for
LEAKY_EXTRA_KG = D("0.9")                 # per roll, never recorded anywhere
LEAKY_ROLLS = 19                          # rolls the weaving plan puts on LEAKY_MACHINE (asserted by the golden test)

WEAVE_HOURS = 6
DYE_HOURS = 6
DYE_BATCH_MAX = 6


def fabric_kg(family: str) -> D:
    """kg = metres x width (m) x GSM / 1000"""
    return ROLL_LENGTH_M * FABRIC_WIDTH_M * GSM[family] / 1000


def yarn_issue_kg(family: str, loom: str) -> D:
    base = fabric_kg(family) * (1 + YARN_WASTE_RATIO)
    return base + (LEAKY_EXTRA_KG if loom == LEAKY_MACHINE else 0)


def yarn_waste_kg(family: str) -> D:
    return fabric_kg(family) * YARN_WASTE_RATIO


# ---------------------------------------------------------------------------
# Act 1: a busy floor at demo "now" — looms weaving WIP greige rolls (open runs), like R-1212 on Loom 5.
# Loom 2 stays free for the stage moment (issue Y-112 to Loom 2 -> refused, LL001), and Loom 3 — the leaky
# loom — is idle, so its month-end figure is untouched. Loom 4 is running when it breaks down live in Act 1.
# ---------------------------------------------------------------------------
BUSY_FLOOR = {"LOOM-1": "Y-101", "LOOM-4": "Y-102", "LOOM-6": "Y-103"}   # loom: yarn lot it is weaving
BUSY_FLOOR_START_HOUR = 8                                               # shift A start on the demo day


# ---------------------------------------------------------------------------
# Money (₹)
# ---------------------------------------------------------------------------
LOOM_RATE_PER_H = D("220")
VAT_RATE_PER_H = D("650")
WEAVER_WAGE_PER_H = D("95")
DYER_WAGE_PER_H = D("100")
DYE_CHEMICALS_PER_BATCH = {"twill": D("4800"), "poplin": D("3000")}
PRICE_PER_M = {"twill": D("185"), "poplin": D("140")}

YARN_LOTS = {
    # code: (family of rolls it feeds, kg received, ₹/kg, supplier code, number of rolls)
    "Y-101": ("twill", D("200"), D("255"), "SUP-NAR", 10),
    "Y-102": ("twill", D("200"), D("262"), "SUP-KAV", 10),
    "Y-103": ("twill", D("200"), D("258"), "SUP-NAR", 10),
    "Y-104": ("twill", D("200"), D("265"), "SUP-NAR", 10),
    "Y-105": ("twill", D("200"), D("260"), "SUP-KAV", 10),
    "Y-106": ("poplin", D("120"), D("250"), "SUP-NAR", 10),
    "Y-107": ("poplin", D("120"), D("252"), "SUP-KAV", 10),
    "Y-108": ("poplin", D("120"), D("248"), "SUP-NAR", 10),
    "Y-109": ("poplin", D("120"), D("255"), "SUP-NAR", 10),
    "Y-110": ("poplin", D("120"), D("251"), "SUP-KAV", 10),
    "Y-111": ("twill", D("100"), D("263"), "SUP-NAR", 3),
    "Y-112": ("twill", D("330"), D("260"), "SUP-KAV", 12),
}

# ---------------------------------------------------------------------------
# Capacity (planning parameters) — metres/day per stage; the minimum is the bottleneck
# ---------------------------------------------------------------------------
STAGE_CAPACITY = {
    "twill": {"weaving": D("250"), "dyeing": D("900")},
    "poplin": {"weaving": D("300"), "dyeing": D("900")},
}

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OrderSpec:
    code: str
    buyer: str
    family: str
    qty_m: int
    order_offset: int       # days from anchor
    promise_offset: int


ORDERS = [
    OrderSpec("SO-0398", "BUY-BLB", "poplin", 1500, -25, -2),
    OrderSpec("SO-0405", "BUY-SAF", "poplin", 1500, -12, 10),
    OrderSpec("SO-0412", "BUY-MER", "twill", 2000, -20, 4),
    OrderSpec("SO-0419", "BUY-CST", "twill", 1500, -15, 7),
]

# ---------------------------------------------------------------------------
# THE Y-112 STORY: 12 rolls, R-1201 … R-1212
# ---------------------------------------------------------------------------
Y112 = "Y-112"
Y112_ROLLS = {
    # roll: (loom, custody, order)
    "R-1201": ("LOOM-2", "rejected", "SO-0412"),
    "R-1202": ("LOOM-5", "rejected", "SO-0412"),
    "R-1203": ("LOOM-2", "rejected", "SO-0412"),
    "R-1204": ("LOOM-5", "at_customer", "SO-0412"),
    "R-1205": ("LOOM-2", "at_customer", "SO-0412"),
    "R-1206": ("LOOM-5", "passed_in_store", "SO-0412"),
    "R-1207": ("LOOM-2", "passed_in_store", "SO-0419"),
    "R-1208": ("LOOM-5", "passed_in_store", "SO-0419"),
    "R-1209": ("LOOM-2", "awaiting_qc", "SO-0419"),
    "R-1210": ("LOOM-5", "awaiting_qc", "SO-0419"),
    "R-1211": ("LOOM-2", "awaiting_qc", "SO-0419"),
    "R-1212": ("LOOM-5", "wip", "SO-0419"),
}
REJECTED_ROLLS = ["R-1201", "R-1202", "R-1203"]
DEFECT = "colour_mismatch"

# Dye batches the Y-112 story depends on (all 6 rolls, so every finished Y-112 roll costs the same)
#   DB-01  Dye Vat 3, Night Shift B  — the 3 rejected rolls + 3 good rolls from other lots
#   DB-02  Dye Vat 1, Day Shift A    — the 5 Y-112 rolls that passed + 1 other
#   DB-03  Dye Vat 2, Day Shift A    — the 3 Y-112 rolls awaiting QC + 3 Y-111 rolls

# ---------------------------------------------------------------------------
# EXPECTED RESULTS — what the golden test asserts and the demo says out loud
# ---------------------------------------------------------------------------
EXPECTED_FIND_CAUSE = {
    # label: (inspected through, rejected through, rate %, inspected elsewhere, rejected elsewhere, rate % elsewhere, verdict)
    "Yarn Lot Y-112": (8, 3, D("37.50"), 100, 4, D("4.00"), "root_cause"),
    "Dye Vat 3":      (33, 3, D("9.09"), 75, 4, D("5.33"), "coincidental"),
    "Night Shift B":  (43, 3, D("6.98"), 65, 4, D("6.15"), "coincidental"),
}
EXPECTED_INSPECTED_TOTAL = 108
EXPECTED_REJECTED_TOTAL = 7

EXPECTED_SCOPE = {
    "rolls_total": 12,
    "rolls_rejected": 3,
    "rolls_at_risk": 9,
    "rolls_passed_in_store": 3,
    "rolls_awaiting_qc": 3,
    "rolls_wip": 1,
    "rolls_at_customer": 2,
    "orders_affected": 2,
    "buyers_affected": 2,
    "buyers_holding_goods": 1,
}
EXPECTED_AT_CUSTOMER = ["R-1204", "R-1205"]


def expected_remake_m() -> D:
    return ROLL_LENGTH_M * len(Y112_ROLLS)                               # 600 m


def expected_throughput() -> D:
    return min(STAGE_CAPACITY["twill"].values())                         # 250 m/day (weaving)


def expected_delay_days(remake_m: D | None = None) -> int:
    remake = expected_remake_m() if remake_m is None else remake_m
    return math.ceil(remake / expected_throughput())                     # ceil(2.4) = 3


def add_working_days(start: date, days: int) -> date:
    """Mon–Sat working week (independent re-implementation of the SQL function)."""
    d = start
    while days > 0:
        d += timedelta(days=1)
        if d.isoweekday() != 7:
            days -= 1
    return d


def expected_order_impact(anchor: date = ANCHOR_DATE) -> dict[str, dict]:
    """Remake joins the weaving queue in promise-date order."""
    out: dict[str, dict] = {}
    cumulative = D(0)
    for o in sorted((o for o in ORDERS if o.code in {"SO-0412", "SO-0419"}),
                    key=lambda o: o.promise_offset):
        rolls = [r for r, (_, _, order) in Y112_ROLLS.items() if order == o.code]
        remake = ROLL_LENGTH_M * len(rolls)
        cumulative += remake
        delay = math.ceil(cumulative / expected_throughput())
        promised = anchor + timedelta(days=o.promise_offset)
        out[o.code] = {
            "rolls": len(rolls),
            "remake_m": remake,
            "delay_days": delay,
            "promised": promised,
            "revised": add_working_days(promised, delay),
        }
    return out


def expected_y112_roll_cost(finished: bool) -> D:
    """Independent cost of one Y-112 roll (all its dye batches have 6 rolls)."""
    _, _, price, _, _ = YARN_LOTS[Y112]
    material = yarn_issue_kg("twill", "LOOM-2") * price                  # Y-112 never touches the leaky loom
    if not finished:                                                     # WIP: conversion absorbed at completion
        return material
    weaving = (LOOM_RATE_PER_H + WEAVER_WAGE_PER_H) * WEAVE_HOURS
    dyeing = ((VAT_RATE_PER_H + DYER_WAGE_PER_H) * DYE_HOURS + DYE_CHEMICALS_PER_BATCH["twill"]) / 6
    return material + weaving + dyeing


def expected_money() -> dict[str, D]:
    finished = expected_y112_roll_cost(True)
    wip = expected_y112_roll_cost(False)
    counts = EXPECTED_SCOPE
    family, received, price, _, n_rolls = YARN_LOTS[Y112]
    used = sum(yarn_issue_kg(family, loom) for loom, _, _ in Y112_ROLLS.values())
    leftover_kg = received - used
    money = {
        "roll_cost_finished": finished,
        "roll_cost_wip": wip,
        "cost_already_incurred": finished * counts["rolls_rejected"],
        "cost_in_factory": finished * (counts["rolls_passed_in_store"] + counts["rolls_awaiting_qc"]),
        "cost_wip": wip * counts["rolls_wip"],
        "cost_at_customer": finished * counts["rolls_at_customer"],
        "quarantined_material_qty": leftover_kg,
        "quarantined_material_value": leftover_kg * price,
    }
    money["recall_exposure"] = money["cost_in_factory"] + money["cost_wip"] + money["cost_at_customer"]
    money["total_exposure"] = (money["cost_already_incurred"] + money["recall_exposure"]
                               + money["quarantined_material_value"])
    return money


if __name__ == "__main__":   # print the locked numbers for the demo script / README
    print("remake m:", expected_remake_m(), "| throughput:", expected_throughput(),
          "| delay days:", expected_delay_days())
    for code, row in expected_order_impact().items():
        print(code, row)
    for k, v in expected_money().items():
        print(f"{k:28s} {v:>12,.2f}")


def expected_mass_balance() -> dict[str, D]:
    """Independent month-end yarn balance (all time): every woven roll (YARN_LOTS) plus the rolls on the looms
    now (BUSY_FLOOR). Open runs carry their issued yarn as WIP; only the leaky loom loses yarn."""
    woven = {"twill": 0, "poplin": 0}
    for family, _, _, _, rolls in YARN_LOTS.values():
        woven[family] += rolls
    on_loom = [(YARN_LOTS[Y112][0], Y112_ROLLS["R-1212"][0])] + [(YARN_LOTS[y][0], loom) for loom, y in BUSY_FLOOR.items()]

    unaccounted = LEAKY_EXTRA_KG * LEAKY_ROLLS
    issued = sum(yarn_issue_kg(f, "") * n for f, n in woven.items()) + unaccounted         + sum(yarn_issue_kg(f, loom) for f, loom in on_loom[1:])           # R-1212 is already in YARN_LOTS
    wip = sum(yarn_issue_kg(f, loom) for f, loom in on_loom)
    finished = dict(woven)
    finished[YARN_LOTS[Y112][0]] -= 1                                       # R-1212 is still on Loom 5
    fabric = sum(fabric_kg(f) * n for f, n in finished.items())
    waste = sum(yarn_waste_kg(f) * n for f, n in finished.items())
    return {"issued_kg": issued, "fabric_kg": fabric, "waste_kg": waste, "wip_kg": wip,
            "unaccounted_kg": unaccounted,
            "unaccounted_pct": (100 * unaccounted / issued).quantize(D("0.01"), rounding=ROUND_HALF_UP)}


# ---------------------------------------------------------------------------
# Workforce register (G1). The seed records, for the ATTENDANCE_DAYS up to and including the demo day, every
# worker on every working day (Mon–Sat) on their usual shift: present, except the listed exceptions.
# Rows the production runs already imply (the operator was there, Sundays included) are kept as they are.
# Exceptions sit on days the worker ran no machine (the seed asserts it). Pay: hourly_wage x shift length
# (12 h) per shift, half for a half day, nothing for absence or leave (wages() in migration 012).
# ---------------------------------------------------------------------------
ATTENDANCE_DAYS = 30
SHIFT_HOURS = 12
WORKER_SHIFT = {"W-01": "A", "W-02": "A", "W-03": "A", "W-04": "B", "W-05": "B", "W-06": "B",
                "D-01": "A", "D-02": "A", "D-03": "B", "Q-01": "A", "Q-02": "B"}
ATTENDANCE_EXCEPTIONS = {          # (worker, days relative to the demo day): status
    ("W-02", -24): "absent", ("W-05", -22): "half_day", ("D-01", -16): "leave",
    ("D-03", -12): "absent", ("Q-01", -3): "half_day", ("Q-02", -9): "leave", ("Q-02", -26): "absent",
}


def expected_register(anchor: date = ANCHOR_DATE) -> dict[str, dict[date, tuple[str, str]]]:
    """worker -> {working day: (status, shift)} for the register the seed writes (Mon–Sat only)."""
    out: dict[str, dict[date, tuple[str, str]]] = {}
    for code, shift in WORKER_SHIFT.items():
        days = {}
        for offset in range(-(ATTENDANCE_DAYS - 1), 1):
            d = anchor + timedelta(days=offset)
            if d.isoweekday() != 7:
                days[d] = (ATTENDANCE_EXCEPTIONS.get((code, offset), "present"), shift)
        out[code] = days
    return out



# ---------------------------------------------------------------------------
# Money in and money out (G2: monthly P&L). An invoice is raised per dispatch at price/m x 50 m x rolls; a goods
# receipt is the yarn bill (kg x ₹/kg). Payments below are what the seed records; nothing else pays anything.
# ---------------------------------------------------------------------------
DISPATCHES = {                     # dispatch: (order, day offset, hour, rolls shipped)
    "DSP-0398-1": ("SO-0398", -2, 11, 30),
    "DSP-0412-1": ("SO-0412", -1, 16, 12),     # includes R-1204 and R-1205 (EXPECTED_AT_CUSTOMER)
}
BUYER_PAYMENTS = [                 # (invoice, ₹ or None = in full, day offset, hour, method)
    ("INV-0398-1", None, -1, 12, "bank_transfer"),
    ("INV-0412-1", D("40000"), -1, 18, "upi"),  # Meridian's part payment on delivery
]
SUPPLIER_PAYMENTS = [              # (yarn lot whose GRN is paid, ₹ or None = in full, day offset, hour, method)
    *[(lot, None, -8, 11, "bank_transfer") for lot in
      ("Y-101", "Y-102", "Y-103", "Y-104", "Y-105", "Y-106", "Y-107", "Y-108")],
    ("Y-109", D("15000"), -3, 11, "cheque"),
]                                  # Y-110, Y-111 on 30-day credit; Y-112 held back (the quality claim)


def invoice_code(dispatch: str) -> str:
    return dispatch.replace("DSP", "INV")


def expected_invoices() -> dict[str, tuple[str, D, int]]:
    """invoice -> (order, amount, issue day offset)."""
    family = {o.code: o.family for o in ORDERS}
    return {invoice_code(d): (order, PRICE_PER_M[family[order]] * ROLL_LENGTH_M * rolls, day)
            for d, (order, day, _, rolls) in DISPATCHES.items()}


def expected_bills() -> dict[str, tuple[str, D]]:
    """goods receipt -> (supplier, amount); every yarn bill is received before day -18."""
    return {f"GRN-{lot}": (supplier, kg * price) for lot, (_, kg, price, supplier, _) in YARN_LOTS.items()}


def expected_pnl(anchor: date, frm: date, to: date) -> dict:
    """Independent revenue, cash and balances for [frm, to]. Wages and COGS come from wages()/lot_cost(), which
    have their own independent tests; the API test checks P&L agrees with them."""
    on = lambda offset: frm <= anchor + timedelta(days=offset) <= to          # noqa: E731
    upto = lambda offset: anchor + timedelta(days=offset) <= to               # noqa: E731
    invoices, bills = expected_invoices(), expected_bills()
    buyer = {o.code: o.buyer for o in ORDERS}
    in_period = {k: v for k, v in invoices.items() if on(v[2])}
    paid_in = {inv: sum((amt or invoices[inv][1] for i, amt, d, _, _ in BUYER_PAYMENTS if i == inv and upto(d)), D(0))
               for inv in invoices}
    bill_paid = {grn: sum((amt or bills[grn][1] for lot, amt, d, _, _ in SUPPLIER_PAYMENTS
                           if f"GRN-{lot}" == grn and upto(d)), D(0)) for grn in bills}
    receivables: dict[str, D] = {}
    for inv, (order, amount, day) in invoices.items():
        if upto(day) and amount - paid_in[inv] > 0:
            receivables[buyer[order]] = receivables.get(buyer[order], D(0)) + amount - paid_in[inv]
    payables: dict[str, D] = {}
    for grn, (supplier, amount) in bills.items():       # all bills predate any demo period end
        if amount - bill_paid[grn] > 0:
            payables[supplier] = payables.get(supplier, D(0)) + amount - bill_paid[grn]
    return {
        "invoices": len(in_period),
        "rolls_invoiced": sum(DISPATCHES[d][3] for d in DISPATCHES if invoice_code(d) in in_period),
        "revenue": sum((v[1] for v in in_period.values()), D(0)),
        "received_from_buyers": sum((amt or invoices[i][1] for i, amt, d, _, _ in BUYER_PAYMENTS if on(d)), D(0)),
        "yarn_bills_paid": sum((amt or bills[f"GRN-{lot}"][1] for lot, amt, d, _, _ in SUPPLIER_PAYMENTS if on(d)), D(0)),
        "receivables": receivables,
        "payables": payables,
    }


# ---------------------------------------------------------------------------
# Yarn availability (G3). Every fabric is woven from one yarn product; the store warns when free yarn (usable
# on hand minus what the open orders still need) drops below the reorder level. Usable = in the yarn store and
# not quarantined. What an order still needs: its unwoven metres (ordered - reserved rolls that are not rejected,
# quarantined or recalled) x yarn_issue_kg per metre. Open orders take usable yarn in due-date order.
# ---------------------------------------------------------------------------
YARN_PRODUCT = "YRN-C40"
YARN_REORDER_LEVEL_KG = {YARN_PRODUCT: D("150")}
RESERVED_ROLLS = {"SO-0412": 20, "SO-0419": 10, "SO-0398": 30, "SO-0405": 18}   # passed rolls, besides Y-112's


def expected_yarn_plan(after_recall: bool, anchor: date = ANCHOR_DATE) -> dict:
    """Independent yarn plan before / after the Y-112 recall."""
    received = sum((kg for _, kg, _, _, _ in YARN_LOTS.values()), D(0))
    usable = received - expected_mass_balance()["issued_kg"]
    held = D(0)
    if after_recall:
        held = expected_money()["quarantined_material_qty"]
        usable -= held
    shipped = {order: rolls for order, _, _, rolls in DISPATCHES.values()}
    impact = expected_order_impact(anchor)
    orders = []
    for o in ORDERS:
        if shipped.get(o.code, 0) * ROLL_LENGTH_M >= o.qty_m:
            continue                                                       # fully dispatched: not open
        y112 = [r for r, (_, custody, order) in Y112_ROLLS.items() if order == o.code]
        good = RESERVED_ROLLS[o.code] + (0 if after_recall else len([r for r in y112 if r not in REJECTED_ROLLS]))
        unwoven = max(D(o.qty_m) - good * ROLL_LENGTH_M, D(0))
        due = anchor + timedelta(days=o.promise_offset)
        if after_recall and o.code in impact:
            due = impact[o.code]["revised"]
        orders.append({"order_code": o.code, "due": due, "covered_m": good * ROLL_LENGTH_M, "unwoven_m": unwoven,
                       "required_kg": (yarn_issue_kg(o.family, "") / ROLL_LENGTH_M * unwoven).quantize(D("0.001"))})
    orders.sort(key=lambda r: (r["due"], r["order_code"]))
    cumulative = D(0)
    for r in orders:
        before = cumulative
        cumulative += r["required_kg"]
        r["available_kg"] = max(usable - before, D(0))
        r["shortfall_kg"] = min(r["required_kg"], max(cumulative - usable, D(0)))
        r["status"] = "short" if r["shortfall_kg"] > 0 else "ok"
    committed = sum((r["required_kg"] for r in orders), D(0))
    return {"on_hand_kg": usable, "quarantined_kg": held, "committed_kg": committed,
            "available_kg": usable - committed, "reorder_level_kg": YARN_REORDER_LEVEL_KG[YARN_PRODUCT],
            "orders": {r["order_code"]: r for r in orders}}
