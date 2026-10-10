-- =====================================================================
-- LoomLedger · 009 · Dispatch guard
-- (008 is reserved for the Shade Guard.)
-- Only rolls that passed quality control, and that are reserved for the order being shipped,
-- may go on a dispatch. The seed has always obeyed this (it asserts it); now the database
-- refuses anything else, whichever client writes:
--   LL004  roll's latest QC result is not 'pass' (never inspected, rework, or rejected)
--   LL005  roll is not reserved for the dispatch's order
-- Quarantine (LL001), stock in FG-STORE (LL002) and one_dispatch_per_roll still apply on top.
-- =====================================================================

CREATE FUNCTION guard_dispatch_line() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_lot_code   text;
    v_order_id   bigint;
    v_order_code text;
    v_result     qc_result;
BEGIN
    SELECT code INTO v_lot_code FROM lot WHERE id = NEW.lot_id;
    SELECT d.order_id, so.code INTO v_order_id, v_order_code
      FROM dispatch d JOIN sales_order so ON so.id = d.order_id
     WHERE d.id = NEW.dispatch_id;

    SELECT result INTO v_result FROM v_latest_qc WHERE lot_id = NEW.lot_id;
    IF v_result IS DISTINCT FROM 'pass' THEN
        RAISE EXCEPTION 'roll % has not passed quality control', v_lot_code
            USING ERRCODE = 'LL004',
                  HINT    = 'Only rolls whose latest inspection is a pass can be dispatched.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM reservation rs JOIN order_line ol ON ol.id = rs.order_line_id
                    WHERE rs.lot_id = NEW.lot_id AND ol.order_id = v_order_id) THEN
        RAISE EXCEPTION 'roll % is not reserved for order %', v_lot_code, v_order_code
            USING ERRCODE = 'LL005',
                  HINT    = 'Reserve the roll for this order before dispatching it.';
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER dispatch_line_guard
    BEFORE INSERT ON dispatch_line
    FOR EACH ROW EXECUTE FUNCTION guard_dispatch_line();
