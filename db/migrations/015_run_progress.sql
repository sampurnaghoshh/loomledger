-- =====================================================================
-- LoomLedger · 015 · How far along is each machine's current run?
-- A loom has no metre counter, so progress is ESTIMATED from facts we do record: the run's planned metres
-- (its output lot's qty), the machine's rated speed (rated_output_per_hour) and the time the machine has
-- actually been running since the run started (machine_state_log; breakdowns and changeovers pause it).
--   planned_hours    = planned_m / rated_m_per_hour
--   productive_hours = time in state 'running' between the run's start and p_at
--   progress_pct     = productive / planned, capped at 100 %; over_plan_hours = what runs past the plan
--   woven_to_plan_at = the moment the running time reached the plan (pauses before it push it later), i.e. since
--                      when the roll has been due off the loom; null while under plan
-- p_at defaults to now(); a fixed p_at gives a reproducible answer (the mock export pins the story clock).
-- =====================================================================
CREATE FUNCTION run_progress(p_at timestamptz DEFAULT now())
RETURNS TABLE (machine_code text, machine_name text, state machine_state, run_code text, lot_code text,
               order_code text, started_at timestamptz, planned_m numeric, rated_m_per_hour numeric,
               planned_hours numeric, productive_hours numeric, paused_hours numeric, progress_pct numeric,
               est_done_m numeric, remaining_hours numeric, over_plan_hours numeric, expected_end timestamptz,
               woven_to_plan_at timestamptz)
LANGUAGE sql STABLE AS $$
    WITH runs AS (
        SELECT m.id AS machine_id, m.code AS machine_code, m.name AS machine_name, m.rated_output_per_hour,
               r.id AS run_id, r.code AS run_code, r.started_at, out.lot_id, out.lot_code, out.qty AS planned_m,
               out.qty / m.rated_output_per_hour AS planned_h
          FROM process_run r
          JOIN machine m ON m.id = r.machine_id
          JOIN LATERAL (SELECT l.id AS lot_id, l.code AS lot_code, l.qty FROM lot l
                         WHERE l.produced_by_run_id = r.id ORDER BY l.code LIMIT 1) out ON true
         WHERE r.started_at <= p_at AND (r.ended_at IS NULL OR r.ended_at > p_at)
           AND m.rated_output_per_hour IS NOT NULL
    ),
    running AS (        -- each 'running' stretch since the run started, clipped to [start, p_at], with the running total
        SELECT seg.run_id, seg.seg_end, seg.h,
               SUM(seg.h) OVER (PARTITION BY seg.run_id ORDER BY seg.seg_start) AS cum_h
          FROM (SELECT ru.run_id, GREATEST(s.started_at, ru.started_at) AS seg_start,
                       LEAST(COALESCE(s.ended_at, p_at), p_at) AS seg_end,
                       EXTRACT(epoch FROM LEAST(COALESCE(s.ended_at, p_at), p_at)
                                          - GREATEST(s.started_at, ru.started_at)) / 3600 AS h
                  FROM runs ru
                  JOIN machine_state_log s ON s.machine_id = ru.machine_id AND s.state = 'running'
                                          AND s.started_at < p_at AND COALESCE(s.ended_at, p_at) > ru.started_at) seg
    ),
    timing AS (
        SELECT ru.*,
               EXTRACT(epoch FROM p_at - ru.started_at) / 3600 AS elapsed_h,
               COALESCE((SELECT SUM(rn.h) FROM running rn WHERE rn.run_id = ru.run_id), 0) AS running_h,
               -- the stretch in which the running total crossed the plan: its end minus the hours past the plan
               (SELECT rn.seg_end - make_interval(secs => ((rn.cum_h - ru.planned_h) * 3600)::double precision)
                  FROM running rn WHERE rn.run_id = ru.run_id AND rn.cum_h >= ru.planned_h
                 ORDER BY rn.cum_h LIMIT 1) AS reached_plan_at,
               (SELECT s.state FROM machine_state_log s
                 WHERE s.machine_id = ru.machine_id AND s.started_at <= p_at
                   AND (s.ended_at IS NULL OR s.ended_at > p_at)
                 ORDER BY s.started_at DESC LIMIT 1) AS state_at
          FROM runs ru
    )
    SELECT t.machine_code, t.machine_name, COALESCE(t.state_at, 'idle'), t.run_code, t.lot_code, so.code,
           t.started_at, t.planned_m, t.rated_output_per_hour,
           round(t.planned_h, 2),
           round(t.running_h, 2),
           round(GREATEST(t.elapsed_h - t.running_h, 0), 2),
           round(100 * LEAST(t.running_h / t.planned_h, 1), 1),
           round(t.planned_m * LEAST(t.running_h / t.planned_h, 1), 1),
           round(GREATEST(t.planned_h - t.running_h, 0), 2),
           round(GREATEST(t.running_h - t.planned_h, 0), 2),
           CASE WHEN t.state_at = 'running' AND t.running_h < t.planned_h      -- paused machines have no ETA
                THEN date_trunc('minute', p_at + make_interval(secs => ((t.planned_h - t.running_h) * 3600)::double precision)) END,
           date_trunc('minute', t.reached_plan_at)
      FROM timing t
      LEFT JOIN reservation rs ON rs.lot_id = t.lot_id
      LEFT JOIN order_line ol  ON ol.id = rs.order_line_id
      LEFT JOIN sales_order so ON so.id = ol.order_id
     ORDER BY t.machine_code;
$$;
