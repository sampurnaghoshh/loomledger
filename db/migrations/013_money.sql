-- =====================================================================
-- LoomLedger · 013 · Money in, money out: payments, bills, and the monthly P&L
-- Reuses what exists: invoice (amount), payment (buyer payments), goods_receipt + lot (a receipt IS the
-- yarn bill: kg x unit_cost), lot_cost() (true cost of rolls), wages() (012), recall_impact() (004).
-- Adds: idempotency + an outstanding-balance guard on buyer payments, supplier payments against yarn bills,
-- balance views, and monthly_pnl(from, to).
--   LL009  a payment larger than what is still outstanding (buyer invoice or supplier bill)
-- =====================================================================

-- ---------- buyer payments ------------------------------------------------
ALTER TABLE payment ADD COLUMN idempotency_key text, ADD COLUMN recorded_by bigint REFERENCES app_user (id);
UPDATE payment SET idempotency_key = 'legacy:payment:' || id WHERE idempotency_key IS NULL;
ALTER TABLE payment ALTER COLUMN idempotency_key SET NOT NULL;
ALTER TABLE payment ADD CONSTRAINT payment_idempotency_key_key UNIQUE (idempotency_key);

-- ---------- supplier payments (a goods receipt is the yarn bill) ------------
CREATE TABLE supplier_payment (
    id               bigserial PRIMARY KEY,
    goods_receipt_id bigint        NOT NULL REFERENCES goods_receipt (id),
    amount           numeric(14,2) NOT NULL CHECK (amount > 0),
    paid_at          timestamptz   NOT NULL,
    method           text          NOT NULL CHECK (method IN ('bank_transfer', 'cheque', 'upi', 'cash')),
    idempotency_key  text          NOT NULL UNIQUE,
    recorded_by      bigint        REFERENCES app_user (id)
);

CREATE VIEW v_invoice_balance AS
SELECT i.id AS invoice_id, i.code, i.order_id, so.buyer_id, i.amount, i.issued_at,
       COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS paid,
       i.amount - COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS outstanding
  FROM invoice i JOIN sales_order so ON so.id = i.order_id;

CREATE VIEW v_bill_balance AS
SELECT gr.id AS goods_receipt_id, gr.code, gr.supplier_id, gr.received_at, b.amount,
       COALESCE((SELECT SUM(sp.amount) FROM supplier_payment sp WHERE sp.goods_receipt_id = gr.id), 0) AS paid,
       b.amount - COALESCE((SELECT SUM(sp.amount) FROM supplier_payment sp WHERE sp.goods_receipt_id = gr.id), 0) AS outstanding
  FROM goods_receipt gr
  CROSS JOIN LATERAL (SELECT round(SUM(l.qty * l.unit_cost), 2) AS amount FROM lot l WHERE l.goods_receipt_id = gr.id) b;

-- ---------- a payment can never exceed what is outstanding -------------------
CREATE FUNCTION guard_payment() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_code text;
    v_outstanding numeric;
BEGIN
    IF TG_TABLE_NAME = 'payment' THEN
        PERFORM 1 FROM invoice WHERE id = NEW.invoice_id FOR UPDATE;        -- serialise payments per invoice
        SELECT code, outstanding INTO v_code, v_outstanding FROM v_invoice_balance WHERE invoice_id = NEW.invoice_id;
    ELSE
        PERFORM 1 FROM goods_receipt WHERE id = NEW.goods_receipt_id FOR UPDATE;
        SELECT code, outstanding INTO v_code, v_outstanding FROM v_bill_balance WHERE goods_receipt_id = NEW.goods_receipt_id;
    END IF;
    IF NEW.amount > v_outstanding THEN
        RAISE EXCEPTION 'payment of % exceeds the % outstanding on %', NEW.amount, v_outstanding, v_code
            USING ERRCODE = 'LL009', DETAIL = v_outstanding::text,
                  HINT = 'Record at most the outstanding amount.';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER payment_guard BEFORE INSERT ON payment FOR EACH ROW EXECUTE FUNCTION guard_payment();
CREATE TRIGGER supplier_payment_guard BEFORE INSERT ON supplier_payment FOR EACH ROW EXECUTE FUNCTION guard_payment();

-- ---------- the owner's books for [p_from, p_to] (mill-time dates, both inclusive) ----------
-- Accrual: revenue = invoices issued in the period; cost of goods sold = lot_cost() of the invoiced rolls,
--   material + machine + chemicals ONLY; labour = wages() for the period. lot_cost's labour component is the
--   operators' pay for run hours — the same people wages() pays — so it is left out of COGS to count it once.
-- Cash: buyer payments received - yarn bills paid - wages (no payroll ledger yet: wages counted as paid as earned).
-- Receivables / payables: as of the end of the period. Recall: exposure of recalls applied in the period —
--   contingent, shown beside the profit, never subtracted (its rolls at the buyer are already in COGS).
CREATE FUNCTION monthly_pnl(p_from date, p_to date)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    WITH ist AS (SELECT p_from AS f, p_to AS t),
    inv AS (
        SELECT i.* FROM invoice i, ist WHERE (i.issued_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN ist.f AND ist.t
    ),
    cogs AS (
        SELECT COALESCE(SUM(c.material), 0) AS material, COALESCE(SUM(c.machine), 0) AS machine,
               COALESCE(SUM(c.chemicals), 0) AS chemicals, COALESCE(SUM(c.labour), 0) AS labour_in_lot_cost,
               count(*) AS rolls
          FROM inv JOIN dispatch_line dl ON dl.dispatch_id = inv.dispatch_id CROSS JOIN LATERAL lot_cost(dl.lot_id) c
    ),
    wage AS (SELECT COALESCE(SUM(gross_wage), 0) AS wages FROM wages(p_from, p_to)),
    revenue AS (SELECT COALESCE(SUM(amount), 0) AS revenue, count(*) AS invoices FROM inv),
    received AS (
        SELECT COALESCE(SUM(p.amount), 0) AS received FROM payment p, ist
         WHERE (p.paid_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN ist.f AND ist.t
    ),
    yarn_paid AS (
        SELECT COALESCE(SUM(sp.amount), 0) AS yarn_paid FROM supplier_payment sp, ist
         WHERE (sp.paid_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN ist.f AND ist.t
    ),
    receivables AS (
        SELECT b.code AS buyer_code, b.name AS buyer, count(*) AS invoices, round(SUM(x.outstanding), 2) AS outstanding
          FROM (SELECT i.id, so.buyer_id,
                       i.amount - COALESCE((SELECT SUM(p.amount) FROM payment p
                                             WHERE p.invoice_id = i.id
                                               AND (p.paid_at AT TIME ZONE 'Asia/Kolkata')::date <= p_to), 0) AS outstanding
                  FROM invoice i JOIN sales_order so ON so.id = i.order_id
                 WHERE (i.issued_at AT TIME ZONE 'Asia/Kolkata')::date <= p_to) x
          JOIN party b ON b.id = x.buyer_id
         WHERE x.outstanding > 0
         GROUP BY b.code, b.name ORDER BY outstanding DESC, b.code
    ),
    payables AS (
        SELECT s.code AS supplier_code, s.name AS supplier, count(*) AS bills, round(SUM(x.outstanding), 2) AS outstanding
          FROM (SELECT bb.supplier_id,
                       bb.amount - COALESCE((SELECT SUM(sp.amount) FROM supplier_payment sp
                                              WHERE sp.goods_receipt_id = bb.goods_receipt_id
                                                AND (sp.paid_at AT TIME ZONE 'Asia/Kolkata')::date <= p_to), 0) AS outstanding
                  FROM v_bill_balance bb WHERE (bb.received_at AT TIME ZONE 'Asia/Kolkata')::date <= p_to) x
          JOIN party s ON s.id = x.supplier_id
         WHERE x.outstanding > 0
         GROUP BY s.code, s.name ORDER BY outstanding DESC, s.code
    ),
    recalls AS (
        SELECT r.code, l.code AS lot_code, r.initiated_at, ri.*
          FROM recall r JOIN lot l ON l.id = r.root_lot_id CROSS JOIN LATERAL recall_impact(r.root_lot_id) ri, ist
         WHERE (r.initiated_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN ist.f AND ist.t
    )
    SELECT jsonb_build_object(
        'from', p_from, 'to', p_to,
        'accrual', jsonb_build_object(
            'invoices', revenue.invoices, 'rolls_invoiced', cogs.rolls,
            'revenue', round(revenue.revenue, 2),
            'material', round(cogs.material, 2), 'machine', round(cogs.machine, 2), 'chemicals', round(cogs.chemicals, 2),
            'cost_of_goods_sold', round(cogs.material + cogs.machine + cogs.chemicals, 2),
            'labour_in_lot_cost_excluded', round(cogs.labour_in_lot_cost, 2),
            'wages', round(wage.wages, 2),
            'profit', round(revenue.revenue - (cogs.material + cogs.machine + cogs.chemicals) - wage.wages, 2)),
        'cash', jsonb_build_object(
            'received_from_buyers', round(received.received, 2), 'yarn_bills_paid', round(yarn_paid.yarn_paid, 2),
            'wages_paid', round(wage.wages, 2), 'wages_paid_basis', 'assumed paid as earned',
            'net_cash', round(received.received - yarn_paid.yarn_paid - wage.wages, 2)),
        'receivables', COALESCE((SELECT jsonb_agg(jsonb_build_object('buyer_code', buyer_code, 'buyer', buyer, 'invoices', invoices, 'outstanding', outstanding)
                                                  ORDER BY outstanding DESC, buyer_code) FROM receivables), '[]'::jsonb),
        'receivables_total', COALESCE((SELECT round(SUM(outstanding), 2) FROM receivables), 0),
        'payables', COALESCE((SELECT jsonb_agg(jsonb_build_object('supplier_code', supplier_code, 'supplier', supplier, 'bills', bills, 'outstanding', outstanding)
                                               ORDER BY outstanding DESC, supplier_code) FROM payables), '[]'::jsonb),
        'payables_total', COALESCE((SELECT round(SUM(outstanding), 2) FROM payables), 0),
        'recalls', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'recall_code', code, 'lot_code', lot_code, 'applied_at', initiated_at,
                        'total_exposure', total_exposure, 'cost_already_incurred', cost_already_incurred,
                        'recall_exposure', recall_exposure, 'quarantined_material_value', quarantined_material_value)
                        ORDER BY initiated_at) FROM recalls), '[]'::jsonb))
      FROM revenue, cogs, wage, received, yarn_paid;
$$;
