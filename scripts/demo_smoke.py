"""Walk the whole LoomLedger demo story over HTTP + WebSocket, exactly as the screens call it.

    python -m scripts.demo_smoke [BASE_URL]        # default http://localhost:8000

Needs a running backend on a freshly seeded database (the recall must not be applied yet);
it refuses otherwise. It CHANGES the database (Loom 4 breaks down, the Y-112 recall is applied),
so reset afterwards — or let the reset script do it: ./scripts/reset_demo.sh --smoke

Every expected value comes from seed/scenario.py (or the API contract in docs/api-mocks);
the numbers printed are the ones the API returned.
Exit code: 0 all ✓ · 1 any ✗ · 2 not runnable (backend unreachable, or database not fresh).

Windows: run from the repo root in PowerShell: python -m scripts.demo_smoke
(the script switches its own output to UTF-8; if ✓/✗ still look garbled, run `chcp 65001` first).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from websockets.sync.client import connect as ws_connect

from seed import scenario as S

PASSWORD = "demo1234"                                 # seeded for every demo user (seed/seed.py)
USERS = {"owner": "owner", "store": "store", "floor": "floor_supervisor", "qc": "qc", "accounts": "accounts"}
GREIGE_FOR = {"twill": "GRG-TWL", "poplin": "GRG-POP"}
MOCKS = Path(__file__).resolve().parent.parent / "docs" / "api-mocks"
NOT_FRESH = 2


class NotRunnable(Exception):
    pass


def money(x) -> str:
    """Indian digit grouping, like the screens: ₹1,23,640."""
    digits = str(round(float(x)))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        head, groups = head[:-2], [head[-2:], *groups]
    return "₹" + ",".join([g for g in (head, *groups) if g] + [tail])


def num(x) -> float:
    return float(x) if isinstance(x, Decimal) else x


class Smoke:
    def __init__(self, base_url: str, out: Callable[[str], None] = print):
        self.base = base_url.rstrip("/")
        self.out = out
        self.http = httpx.Client(base_url=self.base, timeout=15)
        self.tokens: dict[str, str] = {}
        self.failures = 0
        self.anchor = S.ANCHOR_DATE        # the story's demo day; read from the data in Act 2 (seed --anchor moves it)
        self.passes = 0

    # ---------- plumbing ----------
    def check(self, act: str, step: str, ok: bool, detail: str = "") -> bool:
        self.out(f"{'✓' if ok else '✗'} {act} · {step}" + (f" — {detail}" if detail else ""))
        if ok:
            self.passes += 1
        else:
            self.failures += 1
        return ok

    def call(self, method: str, path: str, as_: str | None = None, **kw) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.tokens[as_]}"} if as_ else {}
        return self.http.request(method, path, headers=headers, **kw)

    def ok_json(self, act: str, step: str, res: httpx.Response, status: int = 200):
        if res.status_code != status:
            self.check(act, step, False, f"HTTP {res.status_code}: {res.text[:200]}")
            return None
        return res.json()

    # ---------- gate ----------
    def preflight(self) -> None:
        try:
            health = self.http.get("/api/health").json()
        except httpx.HTTPError as exc:
            raise NotRunnable(f"backend not reachable at {self.base} ({type(exc).__name__}); start uvicorn first") from exc
        if health.get("db") != "ok":
            raise NotRunnable(f"backend is up but its database is not: {health}")
        res = self.http.post("/api/auth/login", json={"email": "qc@everest.test", "password": PASSWORD})
        if res.status_code != 200:
            raise NotRunnable("demo users missing — the database is not seeded")
        token = res.json()["token"]
        preview = self.http.get("/api/recalls/preview", params={"lot_code": S.Y112},
                                headers={"Authorization": f"Bearer {token}"})
        if preview.status_code != 200 or preview.json().get("applied") is not False:
            raise NotRunnable(f"the {S.Y112} recall is already applied: the database is not fresh")

    # ---------- Act 1: a normal day ----------
    def act1(self) -> None:
        act = "Act 1"
        for user, role in USERS.items():
            res = self.http.post("/api/auth/login", json={"email": f"{user}@everest.test", "password": PASSWORD})
            body = self.ok_json(act, f"login {user}@", res)
            if body:
                self.tokens[user] = body["token"]
                self.check(act, f"login {user}@", body["user"]["role"] == role,
                           f"{body['user']['full_name']} ({body['user']['role']})")

        machines = self.ok_json(act, "floor board", self.call("GET", "/api/floor/machines", "floor"))
        if machines is not None:
            states: dict[str, int] = {}
            for m in machines:
                states[m["state"]] = states.get(m["state"], 0) + 1
            running = sorted(m["code"] for m in machines if m["state"] == "running")
            expected = sorted({*S.BUSY_FLOOR, S.Y112_ROLLS["R-1212"][0]})
            self.check(act, "floor board · busy floor", running == expected,
                       f"{len(machines)} machines · " + ", ".join(f"{n} {s}" for s, n in sorted(states.items()))
                       + f" · weaving: {', '.join(running)}")

        self.live_floor_event(act)

        now = self.ok_json(act, "stock now", self.call("GET", "/api/inventory/stock", "store"))
        if now is not None:
            kg = sum(r["qty"] for r in now["rows"] if r["uom"] == "kg")
            m = sum(r["qty"] for r in now["rows"] if r["uom"] == "m")
            self.check(act, "stock now", now["as_of"] is None and len(now["rows"]) > 0,
                       f"{len(now['rows'])} lot positions · {kg:,.1f} kg yarn · {m:,.0f} m fabric")
        yesterday = (datetime.now(ZoneInfo(S.TIMEZONE)) - timedelta(days=1)).replace(microsecond=0)
        past = self.ok_json(act, "stock as of yesterday",
                            self.call("GET", "/api/inventory/stock", "store", params={"as_of": yesterday.isoformat()}))
        if past is not None:
            self.check(act, "stock as of yesterday (time travel)", past["as_of"] is not None,
                       f"as of {past['as_of']} · {len(past['rows'])} lot positions")

    def live_floor_event(self, act: str) -> None:
        """Connect like the Floor Board, then cause the contract's example event and wait for it."""
        event = json.loads((MOCKS / "ws_floor_event.json").read_text(encoding="utf-8"))
        ws_url = self.base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/floor"
        try:
            with ws_connect(f"{ws_url}?token={self.tokens['floor']}", open_timeout=5) as ws:
                time.sleep(0.5)                                    # let the server register the subscription
                res = self.call("POST", f"/api/floor/machines/{event['machine_code']}/state", "floor",
                                json={"state": event["state"], "reason": event["reason"]})
                if not self.check(act, f"set {event['machine_code']} {event['state']}", res.status_code == 200,
                                  f"HTTP {res.status_code}"):
                    return
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    got = json.loads(ws.recv(timeout=max(0.1, deadline - time.monotonic())))
                    if got["machine_code"] == event["machine_code"] and got["ended_at"] is None:
                        self.check(act, "live floor event over /ws/floor", got["state"] == event["state"],
                                   f"{got['machine_code']} → {got['state']} ({got['reason']}) at {got['started_at']}")
                        return
                self.check(act, "live floor event over /ws/floor", False, "no event within 5 s")
        except Exception as exc:                                    # noqa: BLE001 — report, don't crash the run
            self.check(act, "live floor event over /ws/floor", False, f"{type(exc).__name__}: {exc}")

    # ---------- Act 2: something's wrong ----------
    def act2(self) -> None:
        act = "Act 2"
        queue = self.ok_json(act, "QC queue", self.call("GET", "/api/quality/queue", "qc"))
        if queue is not None:
            self.check(act, "QC queue", True, f"{len(queue)} rolls awaiting inspection")
        rejections = self.ok_json(act, "rejections", self.call("GET", "/api/quality/rejections", "qc"))
        if rejections is not None:
            rejected = {r["lot_code"] for r in rejections}
            story = [r for r in rejections if r["lot_code"] == S.REJECTED_ROLLS[0]]
            if story:                      # the story rolls are rejected on the demo day itself
                self.anchor = date.fromisoformat(story[0]["inspected_at"][:10])
            self.check(act, "rejections include the story rolls", set(S.REJECTED_ROLLS) <= rejected,
                       f"{len(rejections)} rejected · {', '.join(S.REJECTED_ROLLS)} ({S.DEFECT})")

        body = self.ok_json(act, "find cause", self.call("POST", "/api/trace/find-cause", "qc",
                                                         json={"lot_codes": S.REJECTED_ROLLS}))
        if body is None:
            return
        factors = {f["factor_label"]: f for f in body["factors"]}
        for label, (insp_in, rej_in, rate_in, insp_out, rej_out, rate_out, verdict) in S.EXPECTED_FIND_CAUSE.items():
            f = factors.get(label)
            if f is None:
                self.check(act, f"find cause · {label}", False, "factor missing")
                continue
            ok = ((f["inspected_through"], f["rejected_through"], f["rate_through_pct"]) == (insp_in, rej_in, num(rate_in))
                  and (f["inspected_outside"], f["rejected_outside"], f["rate_outside_pct"])
                  == (insp_out, rej_out, num(rate_out))
                  and f["verdict"] == verdict)
            self.check(act, f"find cause · {label}", ok,
                       f"{f['rejected_through']}/{f['inspected_through']} = {f['rate_through_pct']}% vs "
                       f"{f['rejected_outside']}/{f['inspected_outside']} = {f['rate_outside_pct']}% "
                       f"(lift {f['lift']}) → {f['verdict']}")
        root = next(label for label, e in S.EXPECTED_FIND_CAUSE.items() if e[-1] == "root_cause")
        self.check(act, "strongest candidate", body["factors"][0]["factor_label"] == root, body["factors"][0]["factor_label"])

    # ---------- Act 3: contain it ----------
    def act3(self) -> dict[str, dict]:
        act = "Act 3"
        before = self.buyer_pages(act, "before the recall")

        preview = self.ok_json(act, "recall preview", self.call("GET", "/api/recalls/preview", "qc",
                                                                params={"lot_code": S.Y112}))
        if preview is not None:
            i = preview["impact"]
            at_buyer = sorted(r["lot_code"] for r in preview["rolls"] if r["custody"] == "at_customer")
            self.check(act, "recall scope", i["rolls_total"] == S.EXPECTED_SCOPE["rolls_total"]
                       and i["rolls_at_risk"] == S.EXPECTED_SCOPE["rolls_at_risk"],
                       f"{i['rolls_total']} rolls = {i['rolls_rejected']} rejected + {i['rolls_at_risk']} at risk")
            self.check(act, "rolls already at the buyer", at_buyer == S.EXPECTED_AT_CUSTOMER,
                       ", ".join(at_buyer))

        first = self.ok_json(act, "apply recall as qc", self.call(
            "POST", "/api/recalls", "qc", json={"lot_code": S.Y112, "reason": f"Colour mismatch traced to {S.Y112}"}), 201)
        if first is not None:
            self.check(act, "apply recall as qc", first["applied"] is True,
                       f"{first['recall_code']} at {first['applied_at']}")
            again = self.call("POST", "/api/recalls", "qc", json={"lot_code": S.Y112, "reason": "pressed again"})
            same = again.status_code == 200 and again.json()["recall_code"] == first["recall_code"] \
                and again.json()["applied_at"] == first["applied_at"]
            self.check(act, "apply again → same recall", same, f"HTTP {again.status_code}, {again.json().get('recall_code')}")

        res = self.call("POST", "/api/production/weaving-runs", "floor", json={
            "machine_code": "LOOM-2", "yarn_lot_code": S.Y112, "product_code": GREIGE_FOR[S.YARN_LOTS[S.Y112][0]],
            "meters_planned": float(S.ROLL_LENGTH_M), "idempotency_key": str(uuid.uuid4())})
        err = res.json().get("error", {}) if res.headers.get("content-type", "").startswith("application/json") else {}
        self.check(act, f"issue {S.Y112} to Loom 2 → refused by PostgreSQL",
                   res.status_code == 409 and err.get("code") == "LOT_QUARANTINED" and err.get("sqlstate") == "LL001",
                   f"HTTP {res.status_code} {err.get('code')} ({err.get('sqlstate')}): {err.get('message')}")
        return before

    # ---------- Act 4: business impact ----------
    def act4(self, before: dict[str, dict]) -> None:
        act = "Act 4"
        preview = self.ok_json(act, "impact", self.call("GET", "/api/recalls/preview", "owner",
                                                        params={"lot_code": S.Y112}))
        if preview is not None:
            i, m = preview["impact"], S.expected_money()
            self.check(act, "remake + delay", i["remake_m"] == num(S.expected_remake_m())
                       and i["throughput_m_per_day"] == num(S.expected_throughput())
                       and i["additional_delay_days"] == S.expected_delay_days(),
                       preview["calculation"]["display"])
            for key, label in (("cost_already_incurred", "already lost"), ("recall_exposure", "newly exposed"),
                               ("quarantined_material_value", "recoverable yarn"), ("total_exposure", "TOTAL exposure")):
                self.check(act, f"money · {label}", i[key] == num(m[key].quantize(Decimal("0.01"))), money(i[key]))
            expected = S.expected_order_impact(self.anchor)
            for o in preview["orders"]:
                e = expected.get(o["order_code"])
                ok = e is not None and o["delay_days"] == e["delay_days"] \
                    and o["revised_promise_date"] == e["revised"].isoformat()
                self.check(act, f"order {o['order_code']}", ok,
                           f"{o['buyer_name']}: {o['promised_date']} → {o['revised_promise_date']} (+{o['delay_days']})")

        after = self.buyer_pages(act, "after the recall")
        for order, e in S.expected_order_impact(self.anchor).items():
            b, a = before.get(order), after.get(order)
            if not (b and a):
                self.check(act, f"buyer page {order}", False, "page missing")
                continue
            ok = (b["expected_date"] == e["promised"].isoformat() and not b["delayed"]
                  and a["expected_date"] == e["revised"].isoformat() and a["delayed"])
            self.check(act, f"buyer phone {order}", ok,
                       f"expected {b['expected_date']} → {a['expected_date']} · latest: {a['updates'][0]['message'][:60]}…")

    def buyer_pages(self, act: str, when: str) -> dict[str, dict]:
        """Public track pages for the affected orders, through the tokens the Orders screen shows."""
        orders = self.ok_json(act, "orders", self.call("GET", "/api/orders", "owner")) or []
        tokens = {o["code"]: o["tracking_token"] for o in orders}
        pages = {}
        for order in S.expected_order_impact(self.anchor):
            res = self.http.get(f"/api/track/{tokens.get(order, 'missing')}")             # public: no login
            if self.check(act, f"buyer page {order} ({when})", res.status_code == 200,
                          f"expected {res.json().get('expected_date')}" if res.status_code == 200 else f"HTTP {res.status_code}"):
                pages[order] = res.json()
        return pages

    # ---------- Close: month end ----------
    def close(self) -> None:
        act = "Close"
        mb = self.ok_json(act, "mass balance", self.call("GET", "/api/finance/mass-balance", "accounts"))
        if mb is not None:
            t, worst, e = mb["totals"], mb["by_machine"][0], S.expected_mass_balance()
            self.check(act, "mass balance", all(t[k] == num(v) for k, v in e.items())
                       and t["unaccounted_kg"] == worst["unaccounted_kg"],
                       f"issued {t['issued_kg']:,} kg = fabric {t['fabric_kg']:,} + waste {t['waste_kg']} + "
                       f"on the looms {t['wip_kg']} + unaccounted {t['unaccounted_kg']} kg = {t['unaccounted_pct']}%")
            self.check(act, "leaky machine", worst["machine_code"] == S.LEAKY_MACHINE and worst["runs"] == S.LEAKY_ROLLS
                       and worst["unaccounted_kg"] == num(S.LEAKY_EXTRA_KG * S.LEAKY_ROLLS),
                       f"{worst['machine_name']}: {worst['unaccounted_kg']} kg = {worst['unaccounted_pct']}%")
        order = next(iter(S.expected_order_impact(self.anchor)))
        costs = self.ok_json(act, "roll costs", self.call("GET", "/api/finance/roll-costs", "accounts",
                                                          params={"order_code": order}))
        if costs is not None:
            y112 = [r for r in costs if r["lot_code"] in S.Y112_ROLLS]
            expected = num(S.expected_y112_roll_cost(True).quantize(Decimal("0.01")))
            self.check(act, f"true cost per roll ({order})", y112 and all(r["total"] == expected for r in y112),
                       f"{len(costs)} rolls · finished {S.Y112} roll = {money(y112[0]['total']) if y112 else '?'}")

    # ---------- run ----------
    def run(self) -> int:
        try:
            self.preflight()
        except NotRunnable as exc:
            self.out(f"✗ not runnable — {exc}")
            self.out("  run ./scripts/reset_demo.sh first (Windows: .\\scripts\\reset_demo.ps1)")
            return NOT_FRESH
        self.out(f"LoomLedger demo smoke against {self.base}")
        self._guarded("Act 1", self.act1)
        self._guarded("Act 2", self.act2)
        before = self._guarded("Act 3", self.act3) or {}
        self._guarded("Act 4", lambda: self.act4(before))
        self._guarded("Close", self.close)
        self.out(f"\n{self.passes} ✓  {self.failures} ✗ — " + ("demo story OK" if not self.failures else "DEMO STORY BROKEN"))
        return 1 if self.failures else 0

    def _guarded(self, act: str, fn: Callable):
        try:
            return fn()
        except Exception as exc:                                    # noqa: BLE001 — one broken act must not hide the rest
            self.check(act, "unexpected error", False, f"{type(exc).__name__}: {exc}")
            return None


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # ✓/✗/₹ on Windows consoles
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    args = parser.parse_args(argv)
    return Smoke(args.base_url).run()


if __name__ == "__main__":
    sys.exit(main())
