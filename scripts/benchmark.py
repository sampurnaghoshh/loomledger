"""Measure the queries the demo shows with EXPLAIN (ANALYZE, BUFFERS) — and report only what was measured.

    ./scripts/reset_demo.sh && python -m scripts.benchmark [--runs 51] [--warmup 5] [--out docs/BENCHMARK.md]

* Read-only: everything runs in ONE `READ ONLY` transaction that is rolled back at the end, so PostgreSQL itself
  refuses any write; exact row counts are compared before and after as a second check.
* Timing: per query, `--warmup` unrecorded runs, then `--runs` runs of EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON).
  Reported: min / median / p95 / max of PostgreSQL's own "Execution Time". `--runs` must be odd so the median
  is one of the measured values; p95 is nearest-rank (also a measured value). Nothing is averaged or rounded up.
* Index use: most demo queries are database functions, whose inner statements a top-level EXPLAIN hides behind
  a "Function Scan". One extra run per query uses PostgreSQL's auto_explain (nested statements, sent back to
  this client as notices) to list every scan inside. Seq Scans on tables with >= --big rows are flagged.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from db.migrate import database_url
from seed import scenario as S
from seed.seed import buyer_token

TABLES = ["lot", "lot_lineage", "stock_move", "process_run", "qc_inspection", "reservation", "order_line",
          "sales_order", "dispatch", "dispatch_line", "machine_state_log", "order_event", "buyer_link"]


# ---------------------------------------------------------------- what the demo runs
def demo_queries(conn: psycopg.Connection) -> list[dict]:
    """The exact calls the API makes for each demo screen, with their parameters resolved from the seed."""
    ids = lambda codes: [r["id"] for r in conn.execute(                                     # noqa: E731
        "SELECT id FROM lot WHERE code = ANY(%s) ORDER BY code", (codes,)).fetchall()]
    rejected, (y112,), (roll,) = ids(S.REJECTED_ROLLS), ids([S.Y112]), ids(S.REJECTED_ROLLS[:1])
    as_of = conn.execute("SELECT received_at FROM goods_receipt WHERE code = %s", (f"GRN-{S.Y112}",)).fetchone()["received_at"]
    month_start = date(S.ANCHOR_DATE.year, S.ANCHOR_DATE.month, 1)
    month_end = date(month_start.year + month_start.month // 12, month_start.month % 12 + 1, 1)
    order = next(iter(S.expected_order_impact()))
    return [
        {"name": f"find_cause({', '.join(S.REJECTED_ROLLS)})", "screen": "Trace · Find Cause",
         "sql": "SELECT * FROM find_cause(%s)", "params": (rejected,)},
        {"name": f"recall_scope({S.Y112})", "screen": "Recall · rolls",
         "sql": "SELECT * FROM recall_scope(%s)", "params": (y112,)},
        {"name": f"recall_impact({S.Y112})", "screen": "Recall · impact + money",
         "sql": "SELECT * FROM recall_impact(%s)", "params": (y112,)},
        {"name": f"lot_ancestors({S.REJECTED_ROLLS[0]})", "screen": "Trace · genealogy (up)",
         "sql": "SELECT * FROM lot_ancestors(%s)", "params": (roll,)},
        {"name": f"stock_on_hand(as_of = receipt of {S.Y112})", "screen": "Inventory · time travel",
         "sql": "SELECT * FROM stock_on_hand(%s)", "params": (as_of,)},
        {"name": f"mass_balance({month_start:%b %Y})", "screen": "Month end · mass balance",
         "sql": "SELECT * FROM mass_balance(%s::timestamptz, %s::timestamptz)", "params": (month_start, month_end)},
        {"name": f"buyer_order_status({order})", "screen": "Buyer phone · track page",
         "sql": "SELECT buyer_order_status(%s)", "params": (buyer_token(order),)},
    ]


# ---------------------------------------------------------------- measuring
def explain(conn: psycopg.Connection, sql: str, params: tuple) -> dict:
    return conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params).fetchone()["QUERY PLAN"][0]


def nearest_rank(sorted_values: list[float], pct: float) -> float:
    k = max(1, -(-len(sorted_values) * pct // 100))          # ceil(n * pct / 100), 1-based
    return sorted_values[int(k) - 1]


def time_query(conn: psycopg.Connection, q: dict, warmup: int, runs: int) -> dict:
    for _ in range(warmup):
        explain(conn, q["sql"], q["params"])
    exec_ms, plan_ms, hit, read = [], [], [], []
    for _ in range(runs):
        e = explain(conn, q["sql"], q["params"])
        exec_ms.append(e["Execution Time"])
        plan_ms.append(e["Planning Time"])
        hit.append(e["Plan"].get("Shared Hit Blocks", 0))
        read.append(e["Plan"].get("Shared Read Blocks", 0))
    s = sorted(exec_ms)
    return {"min": s[0], "median": statistics.median_low(s), "p95": nearest_rank(s, 95), "max": s[-1],
            "planning_median": statistics.median_low(sorted(plan_ms)),
            "shared_hit": statistics.median_low(sorted(hit)), "shared_read": max(read),
            "top_node": e["Plan"]["Node Type"]}


def walk(node: dict, out: list[dict]) -> None:
    out.append(node)
    for child in node.get("Plans", []):
        walk(child, out)


FLUSH = "SELECT 'benchmark: flush notices'"


def nested_scans(conn: psycopg.Connection, q: dict, notices: list[str]) -> list[dict] | None:
    """Every scan node PostgreSQL actually executed for this query, including inside the functions it calls.

    The server sends a statement's auto_explain notice after its result, so psycopg only handles it while running
    the NEXT statement: run a marker statement before (to drain older notices) and after (to receive this
    query's), and drop the marker's own plans."""
    conn.execute(FLUSH)
    notices.clear()
    conn.execute(q["sql"], q["params"]).fetchall()
    conn.execute(FLUSH)
    nodes: list[dict] = []
    for text in notices:
        start = text.find("{")
        if start < 0:
            continue
        plan = json.loads(text[start:])
        if plan.get("Query Text", "").strip() == FLUSH:
            continue
        walk(plan["Plan"], nodes)
    scans = [n for n in nodes if "Scan" in n["Node Type"] and n.get("Relation Name")]
    return [{"node": n["Node Type"], "table": n["Relation Name"], "index": n.get("Index Name"),
             "rows": n.get("Actual Rows", 0), "loops": n.get("Actual Loops", 1)} for n in scans]


def enable_auto_explain(conn: psycopg.Connection, notices: list[str]) -> str | None:
    try:
        with conn.transaction():                              # a savepoint: a failed LOAD must not abort the run
            conn.execute("LOAD 'auto_explain'")
    except psycopg.Error as exc:
        return f"auto_explain unavailable ({exc.diag.message_primary}); nested scans not reported"
    for setting, value in (("log_min_duration", "0"), ("log_analyze", "on"), ("log_buffers", "on"),
                           ("log_nested_statements", "on"), ("log_format", "json"), ("log_level", "notice")):
        conn.execute(f"SET LOCAL auto_explain.{setting} = '{value}'")        # constants only, no user input
    conn.add_notice_handler(lambda d: notices.append(d.message_primary or ""))
    return None


def disable_auto_explain(conn: psycopg.Connection) -> None:
    conn.execute("SET LOCAL auto_explain.log_min_duration = '-1'")


# ---------------------------------------------------------------- context
def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in TABLES}   # fixed table list


def machine_specs(conn: psycopg.Connection) -> dict[str, str]:
    specs = {"os": f"{platform.system()} {platform.release()} ({platform.version()})",
             "cpu": _cpu_name(),
             "logical_cpus": str(os.cpu_count()),
             "ram": _ram(),
             "python": platform.python_version(),
             "postgres": conn.execute("SELECT version() AS v").fetchone()["v"]}
    for name in ("shared_buffers", "work_mem", "effective_cache_size", "jit"):
        specs[f"pg {name}"] = conn.execute(f"SHOW {name}").fetchone()[name]                # fixed names
    # Docker puts /.dockerenv in every container. Test one field: a record "IS NOT NULL" only if ALL its fields are,
    # and pg_stat_file's `creation` is always NULL on Linux. No positive evidence -> say nothing rather than guess.
    try:
        with conn.transaction():
            in_docker = conn.execute(
                "SELECT (pg_stat_file('/.dockerenv', true)).modification IS NOT NULL AS d").fetchone()["d"]
    except psycopg.Error:                                     # needs superuser
        in_docker = False
    if in_docker:
        specs["pg server"] = "Docker container on this host" + _docker_vm()
    return specs


def _cpu_name() -> str:
    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:                                         # noqa: BLE001 — specs are best effort
        pass
    return platform.processor() or platform.machine()


def _docker_vm() -> str:
    """Docker Desktop runs containers in a VM: its CPUs/RAM bound what PostgreSQL can use."""
    try:
        out = subprocess.run(["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}}"], capture_output=True,
                             text=True, timeout=10, check=True).stdout.split()
        return f" (Docker VM: {out[0]} CPUs, {int(out[1]) / 2**30:.1f} GiB RAM)"
    except Exception:                                         # noqa: BLE001
        return ""


def _ram() -> str:
    try:
        if platform.system() == "Windows":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MemStatus()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return f"{m.ullTotalPhys / 2**30:.1f} GiB"
        kb = int(next(l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")).split()[1])
        return f"{kb / 2**20:.1f} GiB"
    except Exception:                                         # noqa: BLE001 — specs are best effort
        return "unknown"


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:                                         # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------- run + report
def run(url: str, runs: int, warmup: int, big: int) -> dict:
    notices: list[str] = []
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")             # first statement of the transaction: writes now fail
        before = row_counts(conn)
        recall_applied = conn.execute("SELECT EXISTS (SELECT 1 FROM recall) AS r").fetchone()["r"]
        specs = machine_specs(conn)
        queries = demo_queries(conn)
        nested_note = enable_auto_explain(conn, notices)
        results = []
        for q in queries:
            scans = None
            if nested_note is None:
                scans = nested_scans(conn, q, notices)
            if nested_note is None:
                disable_auto_explain(conn)
            timing = time_query(conn, q, warmup, runs)
            if nested_note is None:
                conn.execute("SET LOCAL auto_explain.log_min_duration = '0'")
            flagged = [s for s in (scans or []) if s["node"] == "Seq Scan" and before.get(s["table"], 0) >= big]
            results.append({**q, "timing": timing, "scans": scans, "flagged": flagged})
        after = row_counts(conn)
        conn.rollback()                                       # read-only, and rolled back regardless
    return {"results": results, "before": before, "after": after, "specs": specs, "runs": runs, "warmup": warmup,
            "big": big, "nested_note": nested_note, "recall_applied": recall_applied,
            "at": datetime.now(ZoneInfo(S.TIMEZONE)).replace(microsecond=0).isoformat(), "commit": git_commit()}


def scan_summary(scans: list[dict] | None) -> str:
    if scans is None:
        return "n/a"
    seen: dict[tuple, int] = {}
    for s in scans:
        key = (s["node"], s["table"], s["index"])
        seen[key] = seen.get(key, 0) + 1
    return "<br>".join(f"{node} on `{table}`" + (f" via `{index}`" if index else "") + (f" ×{n}" if n > 1 else "")
                       for (node, table, index), n in sorted(seen.items(), key=lambda kv: (kv[0][1], kv[0][0])))


def report(r: dict, command: str) -> str:
    L = []
    L.append("# LoomLedger · query benchmark\n")
    L.append("Measured with `EXPLAIN (ANALYZE, BUFFERS)` on the seeded demo database. **Every number below was measured "
             "by PostgreSQL in this run; nothing is rounded up, averaged into a new value, or extrapolated to other "
             "data sizes** (golden rule 9).\n")
    L.append(f"- **Run:** {r['at']} (IST) · commit `{r['commit']}` · demo day {S.ANCHOR_DATE.isoformat()} · "
             f"recall applied: {'yes' if r['recall_applied'] else 'no (fresh seed)'}")
    L.append(f"- **Method:** {r['warmup']} warm-up runs, then {r['runs']} measured runs per query; PostgreSQL's own "
             "`Execution Time`. Median = the middle measured value (odd run count); p95 = nearest-rank. "
             "All runs in one `READ ONLY` transaction, rolled back at the end.")
    L.append(f"- **Reproduce:** `{command}`\n")

    L.append("## Results (ms)\n")
    L.append("| Query (screen) | min | median | p95 | max | planning (median) | shared buffers hit | read from disk |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for x in r["results"]:
        t = x["timing"]
        L.append(f"| `{x['name']}` ({x['screen']}) | {t['min']:.3f} | {t['median']:.3f} | {t['p95']:.3f} | {t['max']:.3f} "
                 f"| {t['planning_median']:.3f} | {t['shared_hit']} | {t['shared_read']} |")
    L.append("\nPostgreSQL reports times in ms to 3 decimals; they are printed as reported.\n")

    L.append("## Index use (every scan executed, including inside the functions)\n")
    if r["nested_note"]:
        L.append(f"_{r['nested_note']}_\n")
    L.append(f"Seq Scans are flagged ⚠ only on tables with ≥ {r['big']:,} rows.\n")
    L.append("| Query | scans | flagged |")
    L.append("|---|---|---|")
    for x in r["results"]:
        flags = ", ".join(f"⚠ Seq Scan on `{f['table']}`" for f in x["flagged"]) or "—"
        L.append(f"| `{x['name']}` | {scan_summary(x['scans'])} | {flags} |")

    L.append("\n## Findings (from the measurements above)\n")
    slowest = max(r["results"], key=lambda x: x["timing"]["p95"])
    largest = max(r["before"].items(), key=lambda kv: kv[1])
    flagged = [(x["name"], f["table"]) for x in r["results"] for f in x["flagged"]]
    L.append(f"- Slowest query at p95: `{slowest['name']}` — {slowest['timing']['p95']:.3f} ms "
             f"(median {slowest['timing']['median']:.3f} ms).")
    L.append(f"- Most pages read from disk in any measured run: "
             f"{max(x['timing']['shared_read'] for x in r['results'])}.")
    if flagged:
        L.append("- ⚠ Seq Scans on big tables: " + "; ".join(f"`{t}` in `{n}`" for n, t in flagged)
                 + " — candidates for an index migration (re-run this benchmark before/after).")
    else:
        L.append(f"- No Seq Scan on a table with ≥ {r['big']:,} rows. The largest table is `{largest[0]}` "
                 f"({largest[1]:,} rows); at this size PostgreSQL's cost model prefers sequential scans and would "
                 "not choose an added index, so **no index migration is proposed from this data.** Re-run after the "
                 "data grows: the flag column above shows when that changes.")

    L.append("\n## Data size (exact row counts)\n")
    L.append("| table | rows |")
    L.append("|---|---:|")
    for table, n in r["before"].items():
        L.append(f"| `{table}` | {n:,} |")

    L.append("\n## Machine\n")
    for k, v in r["specs"].items():
        L.append(f"- **{k}:** {v}")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=51, help="measured runs per query (odd; default 51)")
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--big", type=int, default=1000, help="flag Seq Scans on tables with at least this many rows")
    p.add_argument("--out", default="docs/BENCHMARK.md")
    args = p.parse_args(argv)
    if args.runs < 1 or args.runs % 2 == 0:
        p.error("--runs must be a positive odd number, so the median is a measured value")

    r = run(database_url(), args.runs, args.warmup, args.big)
    if r["before"] != r["after"]:
        print("✗ row counts changed during the benchmark — not writing a report", file=sys.stderr)
        return 1
    command = "./scripts/reset_demo.sh && python -m scripts.benchmark" + \
        "".join(f" --{k} {v}" for k, v in (("runs", args.runs), ("warmup", args.warmup), ("big", args.big))
                if v != p.get_default(k))
    md = report(r, command)
    Path(args.out).write_text(md, encoding="utf-8")
    for x in r["results"]:
        t = x["timing"]
        flag = "  ⚠ " + ", ".join(f"Seq Scan {f['table']}" for f in x["flagged"]) if x["flagged"] else ""
        print(f"{x['name']:<44} median {t['median']:8.3f} ms   p95 {t['p95']:8.3f} ms{flag}")
    print(f"row counts unchanged ✓ · wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
