-- =====================================================================
-- LoomLedger · 011 · Last working day
-- The mill works Monday–Saturday (add_working_days, working_days_between). On a Sunday the latest
-- production day is the Saturday before, so "today's output" on a Sunday means Saturday's.
--   last_working_day(d) = d for Mon–Sat, d - 1 for a Sunday
-- =====================================================================

CREATE FUNCTION last_working_day(p_day date)
RETURNS date
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN extract(isodow FROM p_day) = 7 THEN p_day - 1 ELSE p_day END;
$$;
