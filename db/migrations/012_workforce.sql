-- =====================================================================
-- LoomLedger · 012 · Workforce: attendance register + wages
-- attendance (001) already holds one row per worker per day (PK worker_id, work_date) with a shift and a
-- status; worker.hourly_wage (001) is the pay rate. This adds what the register and the wage run need:
--   * attendance_batch: one row per register submission (idempotency_key UNIQUE -> a resend is a replay)
--   * guard: no attendance for a future date (LL007) or for an inactive worker (LL008)
--   * shift_hours(shift) and wages(from, to)
-- Pay rule: a shift pays hourly_wage x the shift's length; a half day pays half of that; leave and absence pay
-- nothing. hourly_wage itself is untouched — lot_cost() (004) prices labour on rolls with it.
-- =====================================================================

CREATE TABLE attendance_batch (
    id              bigserial PRIMARY KEY,
    idempotency_key text        NOT NULL UNIQUE,
    work_date       date        NOT NULL,
    shift_id        smallint    NOT NULL REFERENCES shift (id),
    marked_by       bigint      REFERENCES app_user (id),
    marked_at       timestamptz NOT NULL DEFAULT now(),
    marked          int         NOT NULL DEFAULT 0 CHECK (marked >= 0)   -- rows this submission wrote (for replays)
);

ALTER TABLE attendance ADD COLUMN batch_id bigint REFERENCES attendance_batch (id);

CREATE FUNCTION guard_attendance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_code   text;
    v_active boolean;
BEGIN
    IF NEW.work_date > (now() AT TIME ZONE 'Asia/Kolkata')::date THEN
        RAISE EXCEPTION 'attendance for % is in the future', NEW.work_date
            USING ERRCODE = 'LL007', HINT = 'Mark attendance for today or an earlier day.';
    END IF;
    SELECT code, active INTO v_code, v_active FROM worker WHERE id = NEW.worker_id;
    IF NOT v_active THEN
        RAISE EXCEPTION 'worker % is not active', v_code
            USING ERRCODE = 'LL008', HINT = 'Reactivate the worker before marking attendance.';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER attendance_guard
    BEFORE INSERT OR UPDATE ON attendance
    FOR EACH ROW EXECUTE FUNCTION guard_attendance();

-- Length of a shift in hours, also across midnight (B: 20:00-08:00 = 12).
CREATE FUNCTION shift_hours(p_shift_id smallint)
RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN ends_at > starts_at THEN extract(epoch FROM ends_at - starts_at)
                ELSE extract(epoch FROM ends_at - starts_at) + 86400 END / 3600.0
      FROM shift WHERE id = p_shift_id;
$$;

-- Wage run for [p_from, p_to] (both inclusive), one row per active worker, including workers with no rows.
CREATE FUNCTION wages(p_from date, p_to date)
RETURNS TABLE (worker_code text, full_name text, skill machine_stage, hourly_wage numeric,
               days_worked int, shifts_worked numeric, half_days int, absent_days int, leave_days int,
               gross_wage numeric)
LANGUAGE sql STABLE AS $$
    SELECT w.code, w.full_name, w.skill, w.hourly_wage,
           count(*) FILTER (WHERE a.status IN ('present', 'half_day'))::int,
           COALESCE(SUM(CASE a.status WHEN 'present' THEN 1 WHEN 'half_day' THEN 0.5 ELSE 0 END), 0),
           count(*) FILTER (WHERE a.status = 'half_day')::int,
           count(*) FILTER (WHERE a.status = 'absent')::int,
           count(*) FILTER (WHERE a.status = 'leave')::int,
           round(COALESCE(SUM(w.hourly_wage * shift_hours(a.shift_id)
                              * CASE a.status WHEN 'present' THEN 1 WHEN 'half_day' THEN 0.5 ELSE 0 END), 0), 2)
      FROM worker w
      LEFT JOIN attendance a ON a.worker_id = w.id AND a.work_date BETWEEN p_from AND p_to
     WHERE w.active
     GROUP BY w.id
     ORDER BY w.code;
$$;
