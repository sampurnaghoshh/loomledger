-- =====================================================================
-- LoomLedger · 014 · Yarn availability: low-stock warning, order feasibility, receipts for an order
-- "Always know how much raw material we have, get a warning before it runs low; when an order comes in,
-- see whether there is enough yarn to start it." Everything is derived from the ledger and the order book:
--   usable yarn   = on hand in YARN-STORE, lots neither quarantined nor recalled
--   requirement   = weaving_yarn_issue_kg(product, unwoven m) per open order line (007), where unwoven =
--                   ordered - metres already covered by reserved rolls that are not rejected / quarantined /
--                   recalled (so after a recall the remake comes back as a requirement)
--   allocation    = open orders take usable yarn in due-date order (revised date if any), then by code
--   LL010  a goods receipt can only be recorded for an order that is still open
-- =====================================================================

-- ---------- a one-line bill of materials + the reorder level -----------------
ALTER TABLE product
    ADD COLUMN yarn_product_id  bigint,                                      -- fabric: the yarn it is woven from
    ADD COLUMN yarn_kind        product_kind NOT NULL DEFAULT 'yarn' CHECK (yarn_kind = 'yarn'),
    ADD COLUMN reorder_level_kg numeric(12,3) CHECK (reorder_level_kg >= 0),  -- yarn: warn below this
    ADD CONSTRAINT product_yarn_fk FOREIGN KEY (yarn_product_id, yarn_kind) REFERENCES product (id, kind),
    ADD CONSTRAINT product_yarn_only_for_fabric CHECK (yarn_product_id IS NULL OR kind <> 'yarn'),
    ADD CONSTRAINT product_reorder_only_for_yarn CHECK (reorder_level_kg IS NULL OR kind = 'yarn');

-- ---------- gate entry: "which order is this yarn for" ----------------------
ALTER TABLE goods_receipt ADD COLUMN order_id bigint REFERENCES sales_order (id);

CREATE FUNCTION guard_receipt_order() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_code   text;
    v_status order_status;
BEGIN
    IF NEW.order_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT code, status INTO v_code, v_status FROM sales_order WHERE id = NEW.order_id;
    IF v_status IN ('dispatched', 'cancelled') THEN
        RAISE EXCEPTION 'order % is %; yarn can only be received for an open order', v_code, v_status
            USING ERRCODE = 'LL010', HINT = 'Pick an open order, or leave the order empty.';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER goods_receipt_order_guard BEFORE INSERT OR UPDATE OF order_id ON goods_receipt
    FOR EACH ROW EXECUTE FUNCTION guard_receipt_order();

-- ---------- what an order still needs ----------------------------------------
CREATE FUNCTION order_yarn_requirement(p_order_id bigint)
RETURNS TABLE (order_line_id bigint, product_id bigint, yarn_product_id bigint,
               ordered_m numeric, covered_m numeric, unwoven_m numeric, required_kg numeric)
LANGUAGE sql STABLE AS $$
    SELECT ol.id, ol.product_id, p.yarn_product_id, ol.qty_m, c.m,
           GREATEST(ol.qty_m - c.m, 0),
           weaving_yarn_issue_kg(ol.product_id, GREATEST(ol.qty_m - c.m, 0))
      FROM order_line ol
      JOIN product p ON p.id = ol.product_id
      CROSS JOIN LATERAL (
          SELECT COALESCE(SUM(l.qty), 0) AS m
            FROM reservation r
            JOIN lot l             ON l.id = r.lot_id
            JOIN v_roll_custody cu ON cu.lot_id = l.id
           WHERE r.order_line_id = ol.id
             AND cu.custody <> 'rejected'
             AND l.status NOT IN ('quarantined', 'recalled')) c
     WHERE ol.order_id = p_order_id
     ORDER BY ol.id;
$$;

-- ---------- yarn on hand, usable vs held -------------------------------------
CREATE VIEW v_yarn_on_hand AS
WITH flows AS (
    SELECT l.product_id, x.qty,
           (loc.code = 'YARN-STORE' AND l.status NOT IN ('quarantined', 'recalled')) AS usable
      FROM (SELECT to_location_id AS location_id, lot_id, qty FROM stock_move
            UNION ALL
            SELECT from_location_id, lot_id, -qty FROM stock_move) x
      JOIN lot l        ON l.id = x.lot_id AND l.kind = 'yarn'
      JOIN location loc ON loc.id = x.location_id AND loc.kind IN ('internal', 'quarantine')
)
SELECT y.id AS yarn_product_id,
       COALESCE(SUM(f.qty) FILTER (WHERE f.usable), 0)     AS usable_kg,
       COALESCE(SUM(f.qty) FILTER (WHERE NOT f.usable), 0) AS held_kg       -- quarantined / recalled yarn
  FROM product y
  LEFT JOIN flows f ON f.product_id = y.id
 WHERE y.kind = 'yarn'
 GROUP BY y.id;

-- ---------- the yarn plan: open orders in due order, against usable yarn ------
CREATE VIEW v_yarn_plan AS
WITH need AS (
    SELECT so.id AS order_id, so.code AS order_code, COALESCE(so.revised_promise_date, so.promised_date) AS due,
           r.*
      FROM sales_order so
      CROSS JOIN LATERAL order_yarn_requirement(so.id) r
     WHERE so.status NOT IN ('dispatched', 'cancelled')
),
running AS (
    SELECT n.*,
           SUM(n.required_kg) OVER (PARTITION BY n.yarn_product_id ORDER BY n.due, n.order_code, n.order_line_id) AS cumulative_kg
      FROM need n
)
SELECT r.order_id, r.order_code, r.due, r.order_line_id, r.product_id, r.yarn_product_id,
       r.ordered_m, r.covered_m, r.unwoven_m, r.required_kg,
       COALESCE(oh.usable_kg, 0) AS usable_kg,
       GREATEST(COALESCE(oh.usable_kg, 0) - (r.cumulative_kg - r.required_kg), 0) AS available_kg,   -- left for this line
       LEAST(r.required_kg, GREATEST(r.cumulative_kg - COALESCE(oh.usable_kg, 0), 0)) AS shortfall_kg
  FROM running r
  LEFT JOIN v_yarn_on_hand oh ON oh.yarn_product_id = r.yarn_product_id;

-- ---------- low stock: free yarn (usable - committed to open orders) below the reorder level ------
CREATE VIEW v_yarn_availability AS
SELECT y.id AS yarn_product_id, y.code AS product_code, y.name AS product_name,
       COALESCE(oh.usable_kg, 0)                                         AS on_hand_kg,
       COALESCE(oh.held_kg, 0)                                           AS quarantined_kg,
       COALESCE(c.committed_kg, 0)                                       AS committed_kg,
       COALESCE(c.open_orders, 0)                                        AS open_orders,
       COALESCE(oh.usable_kg, 0) - COALESCE(c.committed_kg, 0)           AS available_kg,
       y.reorder_level_kg
  FROM product y
  LEFT JOIN v_yarn_on_hand oh ON oh.yarn_product_id = y.id
  LEFT JOIN (SELECT yarn_product_id, SUM(required_kg) AS committed_kg, count(DISTINCT order_id)::int AS open_orders
               FROM v_yarn_plan GROUP BY yarn_product_id) c ON c.yarn_product_id = y.id
 WHERE y.kind = 'yarn';

CREATE VIEW v_yarn_low_stock AS
SELECT a.*, a.reorder_level_kg - a.available_kg AS below_reorder_kg
  FROM v_yarn_availability a
 WHERE a.available_kg < a.reorder_level_kg;
