-- =====================================================================
-- LoomLedger · 003 · Traceability
-- Walking the family tree (up for causes, down for recalls),
-- deriving stock from the ledger (now, or at any moment in the past),
-- and Find Cause: genealogy + comparative defect-rate analysis.
-- =====================================================================

-- ---------- Family tree walks -------------------------------------------
-- Up: everything this lot was made from.
CREATE FUNCTION lot_ancestors(p_lot_id bigint)
RETURNS TABLE (ancestor_id bigint, depth int)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE up (lot_id, depth) AS (
        SELECT parent_lot_id, 1 FROM lot_lineage WHERE child_lot_id = p_lot_id
        UNION ALL
        SELECT ll.parent_lot_id, up.depth + 1
          FROM up JOIN lot_lineage ll ON ll.child_lot_id = up.lot_id
    ) CYCLE lot_id SET is_cycle USING path      -- defensive: bad data can never loop forever
    SELECT lot_id, min(depth) FROM up WHERE NOT is_cycle GROUP BY lot_id;
$$;

-- Down: everything this lot went into.
CREATE FUNCTION lot_descendants(p_lot_id bigint)
RETURNS TABLE (descendant_id bigint, depth int)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE down (lot_id, depth) AS (
        SELECT child_lot_id, 1 FROM lot_lineage WHERE parent_lot_id = p_lot_id
        UNION ALL
        SELECT ll.child_lot_id, down.depth + 1
          FROM down JOIN lot_lineage ll ON ll.parent_lot_id = down.lot_id
    ) CYCLE lot_id SET is_cycle USING path
    SELECT lot_id, min(depth) FROM down WHERE NOT is_cycle GROUP BY lot_id;
$$;

-- ---------- Stock = sum of the ledger -----------------------------------
CREATE FUNCTION lot_on_hand(p_lot_id bigint, p_location_id bigint, p_as_of timestamptz DEFAULT 'infinity')
RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(CASE WHEN to_location_id = p_location_id THEN qty ELSE -qty END), 0)
      FROM stock_move
     WHERE lot_id = p_lot_id
       AND (to_location_id = p_location_id OR from_location_id = p_location_id)
       AND created_at <= p_as_of;
$$;

-- TIME TRAVEL: what was on the shelves at any moment. Append-only makes this exact.
CREATE FUNCTION stock_on_hand(p_as_of timestamptz DEFAULT 'infinity')
RETURNS TABLE (location_code text, lot_code text, lot_kind product_kind,
               product_code text, qty numeric, uom uom)
LANGUAGE sql STABLE AS $$
    WITH flows AS (
        SELECT to_location_id   AS location_id, lot_id,  qty FROM stock_move WHERE created_at <= p_as_of
        UNION ALL
        SELECT from_location_id AS location_id, lot_id, -qty FROM stock_move WHERE created_at <= p_as_of
    )
    SELECT loc.code, l.code, l.kind, p.code, SUM(f.qty), p.uom
      FROM flows f
      JOIN location loc ON loc.id = f.location_id AND loc.kind IN ('internal', 'quarantine')
      JOIN lot      l   ON l.id   = f.lot_id
      JOIN product  p   ON p.id   = l.product_id
     GROUP BY loc.code, l.code, l.kind, p.code, p.uom
    HAVING SUM(f.qty) > 0;
$$;

-- ---------- Quality views ------------------------------------------------
CREATE VIEW v_latest_qc AS
SELECT DISTINCT ON (lot_id) lot_id, id AS inspection_id, result, defect_type, inspected_at
  FROM qc_inspection
 ORDER BY lot_id, inspected_at DESC, id DESC;

-- Every factor a roll was exposed to anywhere in its ancestry:
-- the yarn lots it came from, every machine that worked on it, every shift it passed through.
CREATE VIEW v_roll_factor AS
WITH RECURSIVE anc (roll_id, lot_id) AS (
    SELECT id, id FROM lot WHERE kind IN ('greige', 'finished')
    UNION
    SELECT anc.roll_id, ll.parent_lot_id
      FROM anc JOIN lot_lineage ll ON ll.child_lot_id = anc.lot_id
)
SELECT anc.roll_id, 'yarn_lot'::text AS factor_kind, l.id AS factor_id, 'Yarn Lot ' || l.code AS factor_label
  FROM anc JOIN lot l ON l.id = anc.lot_id AND l.kind = 'yarn'
UNION
SELECT anc.roll_id, 'machine', m.id, m.name
  FROM anc JOIN lot l ON l.id = anc.lot_id
           JOIN process_run r ON r.id = l.produced_by_run_id
           JOIN machine m     ON m.id = r.machine_id
UNION
SELECT anc.roll_id, 'shift', s.id, s.name
  FROM anc JOIN lot l ON l.id = anc.lot_id
           JOIN process_run r ON r.id = l.produced_by_run_id
           JOIN shift s       ON s.id = r.shift_id;

-- ---------- FIND CAUSE ---------------------------------------------------
-- Naive genealogy says "all bad rolls went through Dye Vat 3, so it's Dye Vat 3".
-- We test every shared factor: defect rate THROUGH it vs defect rate everywhere ELSE.
-- A factor is the root cause only if it covers every selected rejected roll AND
-- its defect rate stands far above the rest (lift >= 3).
CREATE FUNCTION find_cause(p_rejected_lot_ids bigint[])
RETURNS TABLE (
    factor_kind       text,
    factor_label      text,
    selected_covered  int,
    selected_total    int,
    inspected_through int,
    rejected_through  int,
    rate_through_pct  numeric,
    inspected_outside int,
    rejected_outside  int,
    rate_outside_pct  numeric,
    lift              numeric,
    verdict           text
)
LANGUAGE sql STABLE AS $$
    WITH inspected AS (
        SELECT lot_id, result = 'reject' AS rejected FROM v_latest_qc
    ),
    totals AS (
        SELECT count(*) AS n, count(*) FILTER (WHERE rejected) AS r FROM inspected
    ),
    candidate AS (
        SELECT factor_kind, factor_id, factor_label, count(DISTINCT roll_id) AS covered
          FROM v_roll_factor
         WHERE roll_id = ANY (p_rejected_lot_ids)
         GROUP BY factor_kind, factor_id, factor_label
    ),
    through AS (
        SELECT c.factor_kind, c.factor_id, c.factor_label, c.covered,
               count(*)                         AS insp_in,
               count(*) FILTER (WHERE i.rejected) AS rej_in
          FROM candidate c
          JOIN v_roll_factor f ON f.factor_kind = c.factor_kind AND f.factor_id = c.factor_id
          JOIN inspected i     ON i.lot_id = f.roll_id
         GROUP BY c.factor_kind, c.factor_id, c.factor_label, c.covered
    ),
    scored AS (
        SELECT th.*,
               t.n - th.insp_in AS insp_out,
               t.r - th.rej_in  AS rej_out,
               round(100.0 * th.rej_in / NULLIF(th.insp_in, 0), 2)                   AS rate_in,
               round(100.0 * (t.r - th.rej_in) / NULLIF(t.n - th.insp_in, 0), 2)    AS rate_out
          FROM through th CROSS JOIN totals t
    ),
    ranked AS (
        SELECT s.*,
               round(s.rate_in / NULLIF(s.rate_out, 0), 2) AS lift_val,
               -- perfect separation (nothing bad elsewhere) ranks highest
               CASE WHEN s.rate_out = 0 AND s.rate_in > 0 THEN 1e9
                    ELSE s.rate_in / NULLIF(s.rate_out, 0) END AS rank_key
          FROM scored s
    ),
    final AS (
        SELECT r.*,
               row_number() OVER (
                   ORDER BY (r.covered = cardinality(p_rejected_lot_ids)) DESC,
                            r.rank_key DESC NULLS LAST, r.rate_in DESC) AS pos
          FROM ranked r
    )
    SELECT factor_kind, factor_label,
           covered::int, cardinality(p_rejected_lot_ids),
           insp_in::int, rej_in::int, rate_in,
           insp_out::int, rej_out::int, rate_out,
           lift_val,
           CASE
               WHEN covered < cardinality(p_rejected_lot_ids)  THEN 'partial'
               WHEN insp_out = 0                              THEN 'no_comparison'
               WHEN pos = 1 AND rank_key >= 3                 THEN 'root_cause'
               ELSE 'coincidental'
           END
      FROM final
     ORDER BY pos;
$$;

-- ---------- ROLL CUSTODY -------------------------------------------------
-- Where every roll is in its life, derived from facts (lineage, dispatch, open run, QC result),
-- never from lot.status — so recall scope, buyer portal and dashboards always agree,
-- before and after a recall.
CREATE VIEW v_roll_custody AS
SELECT l.id AS lot_id, l.code AS lot_code, l.kind, l.qty AS qty_m, l.status,
       CASE
           WHEN EXISTS (SELECT 1 FROM lot_lineage ll WHERE ll.parent_lot_id = l.id) THEN 'consumed'
           WHEN EXISTS (SELECT 1 FROM dispatch_line dl WHERE dl.lot_id = l.id)       THEN 'at_customer'
           WHEN r.ended_at IS NULL     THEN 'wip'
           WHEN q.result = 'reject'    THEN 'rejected'
           WHEN q.result = 'rework'    THEN 'rework'
           WHEN q.result = 'pass'      THEN 'passed_in_store'
           ELSE 'awaiting_qc'
       END AS custody
  FROM lot l
  JOIN process_run r      ON r.id = l.produced_by_run_id
  LEFT JOIN v_latest_qc q ON q.lot_id = l.id
 WHERE l.kind IN ('greige', 'finished');

-- ---------- RECALL SCOPE -------------------------------------------------
-- Every physical roll downstream of a lot, and where it is right now.
-- (A greige roll that was dyed lives on as its finished roll, so 'consumed' rolls drop out.)
CREATE FUNCTION recall_scope(p_root_lot_id bigint)
RETURNS TABLE (
    lot_id     bigint,
    lot_code   text,
    kind       product_kind,
    qty_m      numeric,
    custody    text,
    order_id   bigint,
    order_code text,
    buyer_id   bigint,
    buyer_name text
)
LANGUAGE sql STABLE AS $$
    SELECT c.lot_id, c.lot_code, c.kind, c.qty_m, c.custody,
           so.id, so.code, b.id, b.name
      FROM lot_descendants(p_root_lot_id) d
      JOIN v_roll_custody c    ON c.lot_id = d.descendant_id AND c.custody <> 'consumed'
      LEFT JOIN reservation rs ON rs.lot_id = c.lot_id
      LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
      LEFT JOIN sales_order so ON so.id = ol.order_id
      LEFT JOIN party b        ON b.id = so.buyer_id
     ORDER BY c.lot_code;
$$;
