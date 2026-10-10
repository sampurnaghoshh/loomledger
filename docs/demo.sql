-- =====================================================================
-- LoomLedger · the 5-minute demo, as raw SQL
-- The UI calls exactly these functions. Run: psql "$DATABASE_URL" -f docs/demo.sql
-- Reset first: ./scripts/reset_demo.sh
-- =====================================================================
\pset pager off
\set ON_ERROR_STOP off

\echo '=== ACT 1 · The floor right now ==='
SELECT code, name, state, current_lot, current_order FROM v_machine_now ORDER BY code;

\echo '=== ACT 2 · Find Cause for the 3 rejected rolls ==='
SELECT factor_label, selected_covered || '/' || selected_total AS covers,
       rejected_through || '/' || inspected_through AS bad_through,
       rate_through_pct AS rate_pct, rate_outside_pct AS elsewhere_pct, lift, verdict
  FROM find_cause(ARRAY(SELECT id FROM lot WHERE code IN ('R-1201', 'R-1202', 'R-1203')));

\echo '=== ACT 3 · Recall scope for Y-112 ==='
SELECT lot_code, custody, order_code, buyer_name
  FROM recall_scope((SELECT id FROM lot WHERE code = 'Y-112'));

\echo '=== ACT 4 · Business impact ==='
\x on
SELECT * FROM recall_impact((SELECT id FROM lot WHERE code = 'Y-112'));
\x off
SELECT order_code, buyer_name, affected_rolls, remake_m, throughput_m_per_day,
       cumulative_remake_m, delay_days, promised_date, revised_promise_date
  FROM recall_order_impact((SELECT id FROM lot WHERE code = 'Y-112'));

\echo '=== Apply the recall (one transaction: freeze, segregate, re-promise, notify) ==='
SELECT apply_recall((SELECT id FROM lot WHERE code = 'Y-112'),
                    'Colour mismatch traced to yarn lot Y-112',
                    (SELECT id FROM app_user WHERE role = 'qc'));

\echo '=== THE TERMINAL MOMENT · try to issue the bad yarn to a loom, bypassing the UI ==='
INSERT INTO stock_move (lot_id, from_location_id, to_location_id, qty, kind, idempotency_key)
SELECT l.id, f.id, t.id, 20, 'issue', 'stage-demo-1'
  FROM lot l, location f, location t
 WHERE l.code = 'Y-112' AND f.code = 'QUARANTINE' AND t.code = 'PRODUCTION';

\echo '=== Buyer A opens their link ==='
SELECT jsonb_pretty(buyer_order_status('4155711b-d0c4-5f02-a2b5-bfd8dd09045d'));

\echo '=== Month-end · where did the yarn go? ==='
SELECT * FROM mass_balance('-infinity', 'infinity');
SELECT * FROM v_yarn_unaccounted_by_machine LIMIT 3;

\echo '=== Time travel · the yarn store the morning Y-112 arrived ==='
SELECT * FROM stock_on_hand((SELECT received_at FROM goods_receipt WHERE code = 'GRN-Y-112'))
 WHERE location_code = 'YARN-STORE' ORDER BY lot_code;
