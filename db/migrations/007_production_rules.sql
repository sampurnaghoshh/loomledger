-- =====================================================================
-- LoomLedger · 007 · Production rules used by the API
-- The yarn-per-metre bridge and the shift calendar are business rules, so they live
-- here rather than in Python. tests/api/test_production.py ties them to seed/scenario.py.
-- =====================================================================

-- Yarn issued to weave p_meters of a fabric: kg = m x width(m) x GSM / 1000, plus 4 % loom waste.
CREATE FUNCTION weaving_yarn_issue_kg(p_product_id bigint, p_meters numeric)
RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT round(p_meters * p.width_m * p.gsm / 1000 * 1.04, 3)
      FROM product p
     WHERE p.id = p_product_id AND p.kind <> 'yarn';
$$;

-- The shift a moment falls in, in mill time. Handles shifts that cross midnight (B: 20:00-08:00).
CREATE FUNCTION shift_at(p_ts timestamptz)
RETURNS smallint
LANGUAGE sql STABLE AS $$
    SELECT s.id
      FROM shift s, LATERAL (SELECT (p_ts AT TIME ZONE 'Asia/Kolkata')::time AS t) x
     WHERE CASE WHEN s.starts_at < s.ends_at THEN x.t >= s.starts_at AND x.t < s.ends_at
                ELSE x.t >= s.starts_at OR x.t < s.ends_at END
     ORDER BY s.id
     LIMIT 1;
$$;
