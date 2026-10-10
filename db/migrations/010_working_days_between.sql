-- =====================================================================
-- LoomLedger · 010 · Working days between two dates
-- The inverse of add_working_days (004): the mill works Monday–Saturday, so a promise that moves from a
-- Saturday to the next Wednesday slipped 3 working days, not 4 calendar days. Used for an order's delay
-- (GET /api/orders) so screens never re-implement the mill calendar.
--   working_days_between(a, b) = number of Mon–Sat days d with a < d <= b   (0 when b <= a)
--   add_working_days(a, working_days_between(a, b)) = b   whenever b is a working day
-- =====================================================================

CREATE FUNCTION working_days_between(p_from date, p_to date)
RETURNS int
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN p_to IS NULL OR p_from IS NULL OR p_to <= p_from THEN 0
                ELSE (SELECT count(*)::int
                        FROM generate_series(p_from + 1, p_to, interval '1 day') AS d
                       WHERE extract(isodow FROM d) <> 7)
           END;
$$;
