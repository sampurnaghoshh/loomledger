-- =====================================================================
-- LoomLedger · 006 · Floor notification payload = the API contract
-- 002 notified {machine_id, state, started_at, ended_at}. The WebSocket contract
-- (docs/api-mocks/ws_floor_event.json) also carries machine_code and reason, so the
-- database emits exactly that shape and the API relays it untouched.
-- Timestamps are rendered in mill time (IST, no DST) whatever the writer's session timezone is.
-- =====================================================================

CREATE FUNCTION ist_iso(p_ts timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(p_ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD"T"HH24:MI:SS') || '+05:30'
$$;

CREATE OR REPLACE FUNCTION notify_machine_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('loomledger_floor', json_build_object(
        'machine_id',   NEW.machine_id,
        'machine_code', (SELECT code FROM machine WHERE id = NEW.machine_id),
        'state',        NEW.state,
        'reason',       NEW.reason,
        'started_at',   ist_iso(NEW.started_at),
        'ended_at',     ist_iso(NEW.ended_at))::text);
    RETURN NEW;
END $$;
