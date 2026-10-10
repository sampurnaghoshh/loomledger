-- =====================================================================
-- LoomLedger · 004 · True cost, recall impact, apply recall
-- =====================================================================

-- ---------- TRUE COST OF A LOT ------------------------------------------
-- Cost flows down the family tree:
--   yarn       = kg received x purchase price
--   any roll   = share of each parent's cost (pro-rata to qty consumed)
--              + share of its own run: machine rate x hours, operator wage x hours, chemicals
-- Run shares are split across all lots the run produced, by quantity.
-- Conversion cost of an unfinished run is absorbed at completion, so WIP carries material only.
CREATE FUNCTION lot_cost(p_lot_id bigint)
RETURNS TABLE (material numeric, machine numeric, labour numeric, chemicals numeric, total numeric)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_lot   lot%ROWTYPE;
    v_run   process_run%ROWTYPE;
    v_hours numeric;
    v_share numeric;
    v_rate  numeric;
    v_wage  numeric;
    p       record;
    pc      record;
BEGIN
    material := 0; machine := 0; labour := 0; chemicals := 0;

    SELECT * INTO v_lot FROM lot WHERE id = p_lot_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lot % does not exist', p_lot_id USING ERRCODE = 'P0002';
    END IF;

    IF v_lot.kind = 'yarn' THEN
        material := v_lot.qty * v_lot.unit_cost;
    ELSE
        FOR p IN
            SELECT ll.parent_lot_id, ll.qty_consumed, pl.qty AS parent_qty
              FROM lot_lineage ll JOIN lot pl ON pl.id = ll.parent_lot_id
             WHERE ll.child_lot_id = p_lot_id
        LOOP
            SELECT * INTO pc FROM lot_cost(p.parent_lot_id);
            material  := material  + pc.material  * p.qty_consumed / p.parent_qty;
            machine   := machine   + pc.machine   * p.qty_consumed / p.parent_qty;
            labour    := labour    + pc.labour    * p.qty_consumed / p.parent_qty;
            chemicals := chemicals + pc.chemicals * p.qty_consumed / p.parent_qty;
        END LOOP;

        SELECT * INTO v_run FROM process_run WHERE id = v_lot.produced_by_run_id;
        IF v_run.ended_at IS NOT NULL THEN
            v_hours := extract(epoch FROM v_run.ended_at - v_run.started_at) / 3600.0;
            SELECT v_lot.qty / SUM(o.qty) INTO v_share FROM lot o WHERE o.produced_by_run_id = v_run.id;
            SELECT rate_per_hour INTO v_rate FROM machine WHERE id = v_run.machine_id;
            SELECT hourly_wage   INTO v_wage FROM worker  WHERE id = v_run.operator_id;
            machine   := machine   + v_rate * v_hours * v_share;
            labour    := labour    + v_wage * v_hours * v_share;
            chemicals := chemicals + v_run.chemical_cost * v_share;
        END IF;
    END IF;

    total := material + machine + labour + chemicals;
    RETURN NEXT;
END $$;

CREATE VIEW v_roll_cost AS
SELECT l.id AS lot_id, l.code AS lot_code, l.kind, l.qty AS qty_m,
       round(c.material, 2)  AS material,
       round(c.machine, 2)   AS machine,
       round(c.labour, 2)    AS labour,
       round(c.chemicals, 2) AS chemicals,
       round(c.total, 2)     AS total,
       round(c.total / l.qty, 2) AS cost_per_m
  FROM lot l CROSS JOIN LATERAL lot_cost(l.id) c
 WHERE l.kind IN ('greige', 'finished');

-- ---------- Calendar ------------------------------------------------------
-- The mill works Monday–Saturday.
CREATE FUNCTION add_working_days(p_date date, p_days int)
RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    d date := p_date;
    n int  := p_days;
BEGIN
    IF p_days < 0 THEN
        RAISE EXCEPTION 'p_days must be >= 0, got %', p_days USING ERRCODE = '22023';
    END IF;
    WHILE n > 0 LOOP
        d := d + 1;
        IF extract(isodow FROM d) <> 7 THEN
            n := n - 1;
        END IF;
    END LOOP;
    RETURN d;
END $$;

-- ---------- RECALL IMPACT: per order -------------------------------------
-- Remake work for each affected order joins the queue at that product's BOTTLENECK stage,
-- in promise-date order. Delay = ceil(cumulative remake metres / bottleneck metres per day).
CREATE FUNCTION recall_order_impact(p_root_lot_id bigint)
RETURNS TABLE (
    order_id             bigint,
    order_code           text,
    buyer_name           text,
    product_code         text,
    affected_rolls       int,
    rolls_at_customer    int,
    at_customer_codes    text,
    remake_m             numeric,
    bottleneck_stage     machine_stage,
    throughput_m_per_day numeric,
    cumulative_remake_m  numeric,
    delay_days           int,
    promised_date        date,
    revised_promise_date date
)
LANGUAGE sql STABLE AS $$
    WITH scope AS (
        SELECT * FROM recall_scope(p_root_lot_id) WHERE order_id IS NOT NULL
    ),
    per_order AS (
        SELECT s.order_id, s.order_code, s.buyer_name, ol.product_id,
               count(*)                                         AS rolls,
               count(*) FILTER (WHERE s.custody = 'at_customer') AS at_cust,
               string_agg(s.lot_code, ', ' ORDER BY s.lot_code)
                   FILTER (WHERE s.custody = 'at_customer')      AS at_cust_codes,
               SUM(s.qty_m)                                     AS remake
          FROM scope s
          JOIN reservation r ON r.lot_id = s.lot_id
          JOIN order_line ol ON ol.id = r.order_line_id
         GROUP BY s.order_id, s.order_code, s.buyer_name, ol.product_id
    ),
    bottleneck AS (
        SELECT DISTINCT ON (product_id) product_id, stage, meters_per_day
          FROM stage_capacity
         ORDER BY product_id, meters_per_day ASC, stage
    ),
    queued AS (
        SELECT po.*, b.stage, b.meters_per_day, so.promised_date, p.code AS product_code,
               SUM(po.remake) OVER (PARTITION BY po.product_id
                                    ORDER BY so.promised_date, so.code) AS cum
          FROM per_order po
          JOIN sales_order so ON so.id = po.order_id
          JOIN product p      ON p.id  = po.product_id
          JOIN bottleneck b   ON b.product_id = po.product_id
    )
    SELECT order_id, order_code, buyer_name, product_code,
           rolls::int, at_cust::int, at_cust_codes, remake,
           stage, meters_per_day, cum,
           ceil(cum / meters_per_day)::int,
           promised_date,
           add_working_days(promised_date, ceil(cum / meters_per_day)::int)
      FROM queued
     ORDER BY promised_date, order_code;
$$;

-- ---------- RECALL IMPACT: the panel --------------------------------------
-- Separates what was already lost, what the recall newly exposes, and what is recoverable.
CREATE FUNCTION recall_impact(p_root_lot_id bigint)
RETURNS TABLE (
    root_lot_code              text,
    rolls_total                int,
    rolls_rejected             int,
    rolls_at_risk              int,
    rolls_passed_in_store      int,
    rolls_awaiting_qc          int,
    rolls_wip                  int,
    rolls_at_customer          int,
    orders_affected            int,
    buyers_affected            int,
    buyers_holding_goods       int,
    remake_m                   numeric,
    bottleneck_stage           machine_stage,
    throughput_m_per_day       numeric,
    additional_delay_days      int,
    cost_already_incurred      numeric,   -- rejected before the recall
    cost_in_factory            numeric,   -- passed / awaiting QC, still with us
    cost_wip                   numeric,   -- on the machine (material only)
    cost_at_customer           numeric,   -- already shipped
    recall_exposure            numeric,   -- newly exposed by the recall
    quarantined_material_qty   numeric,
    quarantined_material_value numeric,   -- recoverable via supplier claim
    total_exposure             numeric
)
LANGUAGE sql STABLE AS $$
    WITH scope AS (
        SELECT s.*, c.total AS cost
          FROM recall_scope(p_root_lot_id) s
          CROSS JOIN LATERAL lot_cost(s.lot_id) c
    ),
    orders AS (SELECT * FROM recall_order_impact(p_root_lot_id)),
    worst AS (
        SELECT * FROM orders ORDER BY delay_days DESC, order_code LIMIT 1
    ),
    root AS (
        SELECT l.code,
               l.qty,
               (SELECT total FROM lot_cost(l.id)) AS root_cost,
               (SELECT COALESCE(SUM(CASE WHEN lt.kind IN ('internal', 'quarantine') THEN m.qty ELSE 0 END)
                              - SUM(CASE WHEN lf.kind IN ('internal', 'quarantine') THEN m.qty ELSE 0 END), 0)
                  FROM stock_move m
                  JOIN location lt ON lt.id = m.to_location_id
                  JOIN location lf ON lf.id = m.from_location_id
                 WHERE m.lot_id = l.id) AS on_hand
          FROM lot l WHERE l.id = p_root_lot_id
    ),
    agg AS (
        SELECT count(*)                                                AS total,
               count(*) FILTER (WHERE custody = 'rejected')            AS rejected,
               count(*) FILTER (WHERE custody = 'passed_in_store')     AS passed,
               count(*) FILTER (WHERE custody = 'awaiting_qc')         AS awaiting,
               count(*) FILTER (WHERE custody = 'wip')                 AS wip,
               count(*) FILTER (WHERE custody = 'at_customer')         AS at_customer,
               count(DISTINCT order_id)                                AS orders,
               count(DISTINCT buyer_id)                                AS buyers,
               count(DISTINCT buyer_id) FILTER (WHERE custody = 'at_customer') AS buyers_holding,
               COALESCE(SUM(qty_m), 0)                                 AS remake,
               COALESCE(SUM(cost) FILTER (WHERE custody = 'rejected'), 0)                         AS c_rej,
               COALESCE(SUM(cost) FILTER (WHERE custody IN ('passed_in_store', 'awaiting_qc', 'rework')), 0) AS c_fac,
               COALESCE(SUM(cost) FILTER (WHERE custody = 'wip'), 0)                              AS c_wip,
               COALESCE(SUM(cost) FILTER (WHERE custody = 'at_customer'), 0)                      AS c_cust
          FROM scope
    )
    SELECT root.code,
           agg.total::int, agg.rejected::int, (agg.total - agg.rejected)::int,
           agg.passed::int, agg.awaiting::int, agg.wip::int, agg.at_customer::int,
           agg.orders::int, agg.buyers::int, agg.buyers_holding::int,
           agg.remake,
           (SELECT bottleneck_stage FROM worst),
           (SELECT throughput_m_per_day FROM worst),
           COALESCE((SELECT delay_days FROM worst), 0),
           round(agg.c_rej, 2), round(agg.c_fac, 2), round(agg.c_wip, 2), round(agg.c_cust, 2),
           round(agg.c_fac + agg.c_wip + agg.c_cust, 2),
           root.on_hand,
           round(root.on_hand * root.root_cost / root.qty, 2),
           round(agg.c_rej + agg.c_fac + agg.c_wip + agg.c_cust + root.on_hand * root.root_cost / root.qty, 2)
      FROM agg, root;
$$;

-- ---------- APPLY RECALL ---------------------------------------------------
-- One transaction: freeze statuses, physically segregate stock, re-promise orders, tell buyers.
-- Idempotent: calling it twice for the same root returns the same recall.
CREATE FUNCTION apply_recall(p_root_lot_id bigint, p_reason text, p_user_id bigint DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_recall_id bigint;
    v_quar_id   bigint;
    v_root      lot%ROWTYPE;
    rec         record;
BEGIN
    SELECT id INTO v_recall_id FROM recall WHERE root_lot_id = p_root_lot_id;
    IF FOUND THEN
        RETURN v_recall_id;
    END IF;

    SELECT * INTO v_root FROM lot WHERE id = p_root_lot_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lot % does not exist', p_root_lot_id USING ERRCODE = 'P0002';
    END IF;

    SELECT id INTO v_quar_id FROM location WHERE kind = 'quarantine' ORDER BY id LIMIT 1;
    IF v_quar_id IS NULL THEN
        RAISE EXCEPTION 'no quarantine location configured' USING ERRCODE = 'P0002';
    END IF;

    INSERT INTO recall (code, root_lot_id, reason, initiated_by)
    VALUES ('RC-' || v_root.code, p_root_lot_id, p_reason, p_user_id)
    RETURNING id INTO v_recall_id;

    -- 1. Freeze: root + every descendant that still physically exists
    UPDATE lot l
       SET status = CASE WHEN EXISTS (SELECT 1 FROM dispatch_line dl WHERE dl.lot_id = l.id)
                         THEN 'recalled'::lot_status ELSE 'quarantined'::lot_status END
     WHERE (l.id = p_root_lot_id OR l.id IN (SELECT descendant_id FROM lot_descendants(p_root_lot_id)))
       AND l.status <> 'consumed';

    -- 2. Segregate: move every in-custody balance into quarantine (allowed by the guard)
    FOR rec IN
        WITH affected AS (
            SELECT p_root_lot_id AS lot_id
            UNION SELECT descendant_id FROM lot_descendants(p_root_lot_id)
        ),
        flows AS (
            SELECT m.lot_id, m.to_location_id AS location_id, m.qty
              FROM stock_move m JOIN affected a ON a.lot_id = m.lot_id
            UNION ALL
            SELECT m.lot_id, m.from_location_id, -m.qty
              FROM stock_move m JOIN affected a ON a.lot_id = m.lot_id
        )
        SELECT f.lot_id, f.location_id, SUM(f.qty) AS qty
          FROM flows f JOIN location loc ON loc.id = f.location_id AND loc.kind = 'internal'
         GROUP BY f.lot_id, f.location_id
        HAVING SUM(f.qty) > 0
    LOOP
        INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind,
                                recall_id, idempotency_key, created_by, note)
        VALUES (rec.lot_id, rec.location_id, v_quar_id, rec.qty, 'quarantine',
                v_recall_id, format('recall:%s:%s:%s', v_recall_id, rec.lot_id, rec.location_id),
                p_user_id, 'Recall RC-' || v_root.code);
    END LOOP;

    -- 3. Re-promise and inform every affected buyer
    FOR rec IN SELECT * FROM recall_order_impact(p_root_lot_id) LOOP
        UPDATE sales_order
           SET revised_promise_date = GREATEST(COALESCE(revised_promise_date, promised_date),
                                               rec.revised_promise_date)
         WHERE id = rec.order_id;

        INSERT INTO order_event (order_id, kind, message, visible_to_buyer)
        VALUES (rec.order_id, 'quality_hold',
                format('Part of your order did not pass our quality check and is being remade. '
                       'New expected dispatch: %s.', to_char(rec.revised_promise_date, 'FMDD Mon YYYY')),
                true);

        IF rec.rolls_at_customer > 0 THEN
            INSERT INTO order_event (order_id, kind, message, visible_to_buyer)
            VALUES (rec.order_id, 'hold_request',
                    format('Please set aside %s delivered roll(s) (%s) pending our quality review. '
                           'We will arrange collection and replacement.',
                           rec.rolls_at_customer, rec.at_customer_codes),
                    true);
        END IF;
    END LOOP;

    RETURN v_recall_id;
END $$;
