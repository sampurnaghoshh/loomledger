-- =====================================================================
-- LoomLedger · 002 · Ledger guards
-- Rules the database enforces no matter which client (UI, API, psql) writes.
-- Custom SQLSTATEs let the API map errors to clear user messages:
--   LL001  movement of a quarantined / recalled lot
--   LL002  insufficient stock at the source location
--   LL003  attempt to rewrite ledger history
-- =====================================================================

-- ---------- 1. The ledger is append-only --------------------------------
CREATE FUNCTION forbid_ledger_rewrite() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'stock_move is append-only: post a correcting move instead of % on move %',
                    TG_OP, OLD.id
        USING ERRCODE = 'LL003';
END $$;

CREATE TRIGGER stock_move_append_only
    BEFORE UPDATE OR DELETE ON stock_move
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_rewrite();

CREATE TRIGGER stock_move_no_truncate
    BEFORE TRUNCATE ON stock_move
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_rewrite();

-- ---------- 2. Quarantine + stock sufficiency ----------------------------
-- Quarantined/recalled lots may only move INTO quarantine, to scrap, or back to the supplier.
-- Internal and quarantine locations can never go negative.
CREATE FUNCTION guard_stock_move() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_lot      lot%ROWTYPE;
    v_to_kind  location_kind;
    v_from     location%ROWTYPE;
    v_on_hand  numeric;
BEGIN
    -- serialise concurrent moves of the same lot so two clerks can't both issue the last 10 kg
    PERFORM pg_advisory_xact_lock(NEW.lot_id);

    SELECT * INTO v_lot  FROM lot      WHERE id = NEW.lot_id;
    SELECT * INTO v_from FROM location WHERE id = NEW.from_location_id;
    SELECT kind INTO v_to_kind FROM location WHERE id = NEW.to_location_id;

    IF v_lot.status IN ('quarantined', 'recalled')
       AND v_to_kind NOT IN ('quarantine', 'scrap', 'supplier') THEN
        RAISE EXCEPTION 'stock movement blocked: lot % is quarantined', v_lot.code
            USING ERRCODE = 'LL001',
                  HINT    = 'Quarantined stock can only go to quarantine, scrap, or back to the supplier.';
    END IF;

    IF v_from.kind IN ('internal', 'quarantine') THEN
        SELECT COALESCE(SUM(CASE WHEN to_location_id = NEW.from_location_id THEN qty ELSE -qty END), 0)
          INTO v_on_hand
          FROM stock_move
         WHERE lot_id = NEW.lot_id
           AND (to_location_id = NEW.from_location_id OR from_location_id = NEW.from_location_id);

        IF v_on_hand < NEW.qty THEN
            RAISE EXCEPTION 'insufficient stock: lot % has % at %, requested %',
                            v_lot.code, v_on_hand, v_from.code, NEW.qty
                USING ERRCODE = 'LL002';
        END IF;
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER stock_move_guard
    BEFORE INSERT ON stock_move
    FOR EACH ROW EXECUTE FUNCTION guard_stock_move();

-- ---------- 3. Audit trail for business-critical tables ------------------
CREATE FUNCTION audit_row() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO audit_log (table_name, row_id, action, old_data, new_data)
    VALUES (TG_TABLE_NAME,
            COALESCE(NEW.id, OLD.id),
            TG_OP,
            CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END);
    RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER lot_audit AFTER UPDATE OF status ON lot
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION audit_row();
CREATE TRIGGER sales_order_audit AFTER UPDATE ON sales_order
    FOR EACH ROW EXECUTE FUNCTION audit_row();
CREATE TRIGGER qc_inspection_audit AFTER INSERT OR UPDATE OR DELETE ON qc_inspection
    FOR EACH ROW EXECUTE FUNCTION audit_row();

-- ---------- 4. Real-time push without third-party services ---------------
-- The API runs LISTEN loomledger_floor / loomledger_ledger and relays to WebSocket clients.
CREATE FUNCTION notify_machine_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('loomledger_floor', json_build_object(
        'machine_id', NEW.machine_id, 'state', NEW.state,
        'started_at', NEW.started_at, 'ended_at', NEW.ended_at)::text);
    RETURN NEW;
END $$;

CREATE TRIGGER machine_state_notify AFTER INSERT OR UPDATE ON machine_state_log
    FOR EACH ROW EXECUTE FUNCTION notify_machine_state();

CREATE FUNCTION notify_stock_move() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('loomledger_ledger', json_build_object(
        'move_id', NEW.id, 'lot_id', NEW.lot_id, 'kind', NEW.kind,
        'from', NEW.from_location_id, 'to', NEW.to_location_id, 'qty', NEW.qty)::text);
    RETURN NEW;
END $$;

CREATE TRIGGER stock_move_notify AFTER INSERT ON stock_move
    FOR EACH ROW EXECUTE FUNCTION notify_stock_move();
