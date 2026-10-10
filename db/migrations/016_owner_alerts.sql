-- =====================================================================
-- LoomLedger · 016 · Owner alerts: a live channel for things the owner must hear about NOW
-- A separate NOTIFY channel, loomledger_alerts (never /ws/floor, whose clients apply every event by machine):
--   recall    : a recall was committed. Fired by a DEFERRED constraint trigger on recall INSERT, i.e. at COMMIT of
--               apply_recall's transaction, after it froze and moved everything, so the numbers are final.
--               PostgreSQL delivers NOTIFY only on commit: a rolled-back recall never alerts, and re-applying
--               (apply_recall is idempotent: no new recall row) never alerts twice.
--   breakdown : a machine went into 'breakdown' (machine, reason, time).
-- The payload is built here from recall_impact / recall_order_impact / recall_scope; the API relays it untouched.
-- =====================================================================

CREATE FUNCTION recall_alert_payload(p_recall_id bigint) RETURNS json
LANGUAGE sql STABLE AS $$
    SELECT json_build_object(
        'kind',              'recall',
        'recall_code',       rc.code,
        'root_lot_code',     i.root_lot_code,
        'reason',            rc.reason,
        'applied_at',        ist_iso(rc.initiated_at),
        'rolls_total',       i.rolls_total,
        'rolls_rejected',    i.rolls_rejected,
        'rolls_at_risk',     i.rolls_at_risk,
        'rolls_at_customer', i.rolls_at_customer,
        'at_buyers',         COALESCE((SELECT json_agg(json_build_object('buyer', b.buyer_name, 'rolls', b.rolls)
                                                       ORDER BY b.buyer_name)
                                         FROM (SELECT s.buyer_name, json_agg(s.lot_code ORDER BY s.lot_code) AS rolls
                                                 FROM recall_scope(rc.root_lot_id) s
                                                WHERE s.custody = 'at_customer'
                                                GROUP BY s.buyer_name) b), '[]'::json),
        'orders_affected',   i.orders_affected,
        'buyers_affected',   i.buyers_affected,
        'delay_days',        i.additional_delay_days,
        'orders',            COALESCE((SELECT json_agg(json_build_object(
                                                 'order_code', o.order_code, 'buyer', o.buyer_name,
                                                 'delay_days', o.delay_days, 'promised_date', o.promised_date,
                                                 'revised_promise_date', o.revised_promise_date)
                                               ORDER BY o.promised_date, o.order_code)
                                         FROM recall_order_impact(rc.root_lot_id) o), '[]'::json),
        'total_exposure',    i.total_exposure)
      FROM recall rc
      CROSS JOIN LATERAL recall_impact(rc.root_lot_id) i
     WHERE rc.id = p_recall_id;
$$;

CREATE FUNCTION notify_recall_alert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('loomledger_alerts', recall_alert_payload(NEW.id)::text);
    RETURN NULL;
END $$;

-- Deferred: runs at COMMIT, after the rest of apply_recall (freeze, quarantine moves, re-promise) is done.
CREATE CONSTRAINT TRIGGER recall_alert
    AFTER INSERT ON recall
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION notify_recall_alert();

CREATE FUNCTION breakdown_alert_payload(p_machine_id bigint, p_reason text, p_started_at timestamptz) RETURNS json
LANGUAGE sql STABLE AS $$
    SELECT json_build_object('kind', 'breakdown', 'machine_code', m.code, 'machine_name', m.name,
                             'reason', p_reason, 'started_at', ist_iso(p_started_at))
      FROM machine m WHERE m.id = p_machine_id;
$$;

CREATE FUNCTION notify_breakdown_alert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('loomledger_alerts', breakdown_alert_payload(NEW.machine_id, NEW.reason, NEW.started_at)::text);
    RETURN NULL;
END $$;

CREATE TRIGGER breakdown_alert
    AFTER INSERT ON machine_state_log
    FOR EACH ROW WHEN (NEW.state = 'breakdown')
    EXECUTE FUNCTION notify_breakdown_alert();
