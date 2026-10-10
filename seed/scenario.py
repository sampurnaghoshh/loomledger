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
