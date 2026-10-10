"""Production business flows: weaving runs. Each write is one transaction; the database's guards
(LL001 quarantine, LL002 stock, no_machine_double_booking) decide whether it commits."""
from __future__ import annotations

import psycopg

from app import ledger
from app.db import write_tx
from app.errors import ApiError, is_idempotency_replay
from app.modules.production import repository as repo
from app.modules.production.schemas import FinishWeavingRequest, StartWeavingRequest


def _not_found(field: str, message: str) -> ApiError:
    return ApiError("NOT_FOUND", message, 404, fields={field: "not found"})


def start_weaving(conn: psycopg.Connection, req: StartWeavingRequest, user: dict) -> tuple[dict, bool]:
    """Put a loom to work: open a run, create its greige roll (WIP), issue the yarn to it and record
    that the roll descends from that yarn lot. Returns (result, created)."""
    original = repo.start_replay(conn, req.idempotency_key)
    if original:
        return original, False
    try:
        with write_tx(conn):
            machine = repo.machine(conn, req.machine_code)
            if machine is None:
                raise _not_found("machine_code", f"Machine {req.machine_code} not found.")
            product = repo.greige_product(conn, req.product_code)
            if product is None:
                raise _not_found("product_code", f"Greige product {req.product_code} not found.")
            yarn = repo.yarn_lot(conn, req.yarn_lot_code)
            if yarn is None:
                raise _not_found("yarn_lot_code", f"Yarn lot {req.yarn_lot_code} not found.")
            line_id = None
            if req.order_code is not None:
                line_id = repo.order_line_id(conn, req.order_code)
                if line_id is None:
                    raise _not_found("order_code", f"Order {req.order_code} not found.")
            op = repo.operator(conn, "weaving", req.operator_code)
            if op is None:
                if req.operator_code is not None:
                    raise _not_found("operator_code", f"Worker {req.operator_code} not found.")
                raise ApiError("VALIDATION_FAILED", "No free weaver is available for this run.", 422,
                               fields={"operator_code": "no free weaver; name one"})

            n = repo.next_roll_number(conn)
            run_code, lot_code = f"WV-R-{n}", f"R-{n}-G"
            run_id = repo.insert_run(conn, run_code, machine["id"], "weaving", op["id"])
            lot_id = repo.insert_greige_lot(conn, lot_code, product["id"], req.meters_planned, run_id)
            kg = repo.yarn_issue_kg(conn, product["id"], req.meters_planned)
            ledger.post_move(conn, lot_id=yarn["id"], src=repo.YARN_STORE, dst=repo.PRODUCTION, qty=kg,
                             kind="issue", idempotency_key=req.idempotency_key, user_id=user["id"], run_id=run_id)
            repo.insert_lineage(conn, yarn["id"], lot_id, kg)
            if line_id is not None:
                repo.reserve(conn, lot_id, line_id)
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and (original := repo.start_replay(conn, req.idempotency_key)):
            return original, False
        raise
    except psycopg.errors.ForeignKeyViolation as exc:
        if exc.diag.constraint_name == "process_run_machine_id_stage_fkey":
            raise ApiError("VALIDATION_FAILED", f"{req.machine_code} is not a weaving machine.", 422,
                           fields={"machine_code": "not a weaving machine"}, sqlstate=exc.sqlstate) from exc
        raise
    return {"run_code": run_code, "lot_code": lot_code, "yarn_issued_kg": kg}, True


def finish_weaving(conn: psycopg.Connection, run_code: str, req: FinishWeavingRequest, user: dict) -> dict:
    """Take the roll off the loom: close the run (its machine and labour hours now count in lot_cost),
    scrap the recorded waste, and move the greige roll into the greige store."""
    original = repo.finish_replay(conn, req.idempotency_key)
    if original:
        return original
    try:
        with write_tx(conn):
            run = repo.lock_weaving_run(conn, run_code)
            if run is None:
                raise ApiError("NOT_FOUND", f"Weaving run {run_code} not found.", 404)
            if run["ended_at"] is not None:
                raise ApiError("VALIDATION_FAILED", f"Run {run_code} is already finished.", 422,
                               fields={"run_code": "already finished"})
            repo.end_run(conn, run["id"])
            if req.waste_kg > 0:
                ledger.post_move(conn, lot_id=run["yarn_lot_id"], src=repo.PRODUCTION, dst=repo.SCRAP,
                                 qty=req.waste_kg, kind="scrap", idempotency_key=f"{req.idempotency_key}:waste",
                                 user_id=user["id"], run_id=run["id"])
            ledger.post_move(conn, lot_id=run["lot_id"], src=repo.PRODUCTION, dst=repo.GREIGE_STORE,
                             qty=run["meters"], kind="production", idempotency_key=req.idempotency_key,
                             user_id=user["id"], run_id=run["id"])
            repo.activate_lot(conn, run["lot_id"])
    except psycopg.errors.UniqueViolation as exc:
        if is_idempotency_replay(exc) and (original := repo.finish_replay(conn, req.idempotency_key)):
            return original
        raise
    return {"run_code": run["code"], "lot_code": run["lot_code"], "meters": run["meters"]}
