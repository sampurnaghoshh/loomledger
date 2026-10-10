-- =====================================================================
-- LoomLedger · 005 · Floor board, buyer portal, mass balance
-- =====================================================================

-- ---------- FLOOR BOARD ---------------------------------------------------
-- What every machine is doing right now, and on which job.
CREATE VIEW v_machine_now AS
SELECT m.id AS machine_id, m.code, m.name, m.stage,
       COALESCE(s.state, 'idle'::machine_state) AS state,
       s.started_at AS state_since,
       s.reason,
       r.code  AS current_run,
       out.lot_code AS current_lot,
       so.code AS current_order
  FROM machine m
  LEFT JOIN machine_state_log s ON s.machine_id = m.id AND s.ended_at IS NULL
  LEFT JOIN process_run r       ON r.machine_id = m.id AND r.ended_at IS NULL
  LEFT JOIN LATERAL (
        SELECT l.id AS lot_id, l.code AS lot_code FROM lot l
         WHERE l.produced_by_run_id = r.id ORDER BY l.code LIMIT 1) out ON true
  LEFT JOIN reservation rs ON rs.lot_id = out.lot_id
  LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
  LEFT JOIN sales_order so ON so.id = ol.order_id
 WHERE m.active;

-- Metres finished per machine on a given day (default: today, mill time).
CREATE FUNCTION floor_output(p_day date DEFAULT (now() AT TIME ZONE 'Asia/Kolkata')::date)
RETURNS TABLE (machine_code text, machine_name text, stage machine_stage, runs_completed int, meters numeric)
LANGUAGE sql STABLE AS $$
    SELECT m.code, m.name, m.stage, count(DISTINCT r.id)::int, COALESCE(SUM(l.qty), 0)
      FROM machine m
      LEFT JOIN process_run r ON r.machine_id = m.id AND r.ended_at IS NOT NULL
                              AND (r.ended_at AT TIME ZONE 'Asia/Kolkata')::date = p_day
      LEFT JOIN lot l         ON l.produced_by_run_id = r.id
     GROUP BY m.code, m.name, m.stage
     ORDER BY m.code;
$$;

-- Availability over a window, from the state log (the 'A' of OEE).
CREATE FUNCTION machine_availability(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (machine_code text, running_h numeric, breakdown_h numeric, availability_pct numeric)
LANGUAGE sql STABLE AS $$
    WITH clipped AS (
        SELECT s.machine_id, s.state,
               extract(epoch FROM LEAST(COALESCE(s.ended_at, p_to), p_to)
                                - GREATEST(s.started_at, p_from)) / 3600.0 AS h
          FROM machine_state_log s
         WHERE tstzrange(s.started_at, s.ended_at, '[)') && tstzrange(p_from, p_to, '[)')
    )
    SELECT m.code,
           round(COALESCE(SUM(h) FILTER (WHERE state = 'running'), 0), 2),
           round(COALESCE(SUM(h) FILTER (WHERE state = 'breakdown'), 0), 2),
           round(100.0 * COALESCE(SUM(h) FILTER (WHERE state = 'running'), 0)
                       / NULLIF(SUM(h) FILTER (WHERE state IN ('running', 'breakdown')), 0), 1)
      FROM machine m LEFT JOIN clipped c ON c.machine_id = m.id
     GROUP BY m.code ORDER BY m.code;
$$;

-- ---------- MASS BALANCE --------------------------------------------------
-- Yarn is weighed (kg), fabric is measured (m). Bridge: kg = m x width(m) x GSM / 1000.
-- For every weaving run: issued = fabric + recorded waste + still-on-loom + UNACCOUNTED.
CREATE VIEW v_yarn_balance_by_run AS
SELECT r.id AS run_id, r.code AS run_code, m.code AS machine_code, m.name AS machine_name,
       r.started_at, r.ended_at,
       COALESCE(io.issued, 0) AS issued_kg,
       COALESCE(io.waste, 0)  AS waste_kg,
       CASE WHEN r.ended_at IS NULL THEN 0 ELSE COALESCE(fab.kg, 0) END                        AS fabric_kg,
       CASE WHEN r.ended_at IS NULL THEN COALESCE(io.issued, 0) - COALESCE(io.waste, 0) ELSE 0 END AS wip_kg,
       CASE WHEN r.ended_at IS NULL THEN 0
            ELSE COALESCE(io.issued, 0) - COALESCE(io.waste, 0) - COALESCE(fab.kg, 0) END       AS unaccounted_kg
  FROM process_run r
  JOIN machine m ON m.id = r.machine_id
  LEFT JOIN LATERAL (
        SELECT SUM(sm.qty) FILTER (WHERE sm.kind = 'issue') AS issued,
               SUM(sm.qty) FILTER (WHERE sm.kind = 'scrap') AS waste
          FROM stock_move sm JOIN lot y ON y.id = sm.lot_id AND y.kind = 'yarn'
         WHERE sm.process_run_id = r.id) io ON true
  LEFT JOIN LATERAL (
        SELECT SUM(l.qty * p.gsm * p.width_m / 1000.0) AS kg
          FROM lot l JOIN product p ON p.id = l.product_id
         WHERE l.produced_by_run_id = r.id) fab ON true
 WHERE r.stage = 'weaving';

CREATE FUNCTION mass_balance(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (received_kg numeric, issued_kg numeric, fabric_kg numeric, waste_kg numeric,
               wip_kg numeric, unaccounted_kg numeric, unaccounted_pct numeric)
LANGUAGE sql STABLE AS $$
    WITH runs AS (
        SELECT * FROM v_yarn_balance_by_run WHERE started_at >= p_from AND started_at < p_to
    )
    SELECT (SELECT COALESCE(SUM(sm.qty), 0) FROM stock_move sm
             WHERE sm.kind = 'receipt' AND sm.created_at >= p_from AND sm.created_at < p_to),
           round(SUM(issued_kg), 3), round(SUM(fabric_kg), 3), round(SUM(waste_kg), 3),
           round(SUM(wip_kg), 3), round(SUM(unaccounted_kg), 3),
           round(100.0 * SUM(unaccounted_kg) / NULLIF(SUM(issued_kg), 0), 2)
      FROM runs;
$$;

CREATE VIEW v_yarn_unaccounted_by_machine AS
SELECT machine_code, machine_name,
       count(*)                       AS runs,
       round(SUM(issued_kg), 3)       AS issued_kg,
       round(SUM(unaccounted_kg), 3)  AS unaccounted_kg,
       round(100.0 * SUM(unaccounted_kg) / NULLIF(SUM(issued_kg), 0), 2) AS unaccounted_pct
  FROM v_yarn_balance_by_run
 GROUP BY machine_code, machine_name
 ORDER BY unaccounted_kg DESC;

-- ---------- BUYER PORTAL --------------------------------------------------
-- Everything a buyer may see about their order, through an unguessable expiring token.
-- Returns NULL for an unknown or expired token (the API answers 404 either way).
CREATE FUNCTION buyer_order_status(p_token uuid)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    WITH link AS (
        SELECT order_id FROM buyer_link WHERE token = p_token AND expires_at > now()
    ),
    rolls AS (
        SELECT c.custody, c.status, c.qty_m
          FROM link
          JOIN order_line ol  ON ol.order_id = link.order_id
          JOIN reservation rs ON rs.order_line_id = ol.id
          JOIN v_roll_custody c ON c.lot_id = rs.lot_id
    ),
    stages AS (
        SELECT COALESCE(SUM(qty_m) FILTER (WHERE status IN ('quarantined', 'recalled') AND custody <> 'at_customer'), 0) AS on_hold_m,
               COALESCE(SUM(qty_m) FILTER (WHERE custody = 'wip' AND status NOT IN ('quarantined', 'recalled')), 0) AS weaving_m,
               COALESCE(SUM(qty_m) FILTER (WHERE custody = 'awaiting_qc' AND status NOT IN ('quarantined', 'recalled')), 0) AS quality_check_m,
               COALESCE(SUM(qty_m) FILTER (WHERE custody = 'passed_in_store' AND status NOT IN ('quarantined', 'recalled')), 0) AS ready_m,
               COALESCE(SUM(qty_m) FILTER (WHERE custody = 'at_customer'), 0) AS dispatched_m
          FROM rolls
    )
    SELECT jsonb_build_object(
               'order',         so.code,
               'buyer',         b.name,
               'product',       p.name,
               'ordered_m',     (SELECT SUM(qty_m) FROM order_line WHERE order_id = so.id),
               'promised_date', so.promised_date,
               'expected_date', COALESCE(so.revised_promise_date, so.promised_date),
               'delayed',       so.revised_promise_date IS NOT NULL
                                AND so.revised_promise_date > so.promised_date,
               'progress',      to_jsonb(stages),
               'updates',       COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                              'at', e.created_at, 'message', e.message)
                                              ORDER BY e.created_at DESC, e.id DESC)
                                            FROM order_event e
                                           WHERE e.order_id = so.id AND e.visible_to_buyer), '[]'::jsonb))
      FROM link
      JOIN sales_order so ON so.id = link.order_id
      JOIN party b        ON b.id = so.buyer_id
      JOIN LATERAL (SELECT product_id FROM order_line WHERE order_id = so.id ORDER BY id LIMIT 1) ol1 ON true
      JOIN product p      ON p.id = ol1.product_id
      CROSS JOIN stages;
$$;
