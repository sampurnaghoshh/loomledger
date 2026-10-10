-- =====================================================================
-- LoomLedger · 008 · Shade Guard
-- Rolls from different dye batches never match exactly in shade, so a buyer who gets a mixed
-- shipment sees colour bands across garments. One dispatch = one dye batch, unless someone
-- records why mixing is acceptable (e.g. the buyer approved it). The reason is kept on the dispatch.
--   LL006  dispatch mixes dye batches and has no shade_override_reason
--          (DETAIL = the batches involved, comma-separated, for the API's fields.batches)
--
-- Numbered 008 but merged after 009: db/migrate.py tracks applied files by name, so existing
-- databases apply this once, after 009; fresh ones apply it before 009. It therefore depends on
-- nothing from 009. Same-event triggers fire in name order, so 009's dispatch_line_guard (QC pass,
-- reserved for the order) always runs before dispatch_line_shade_guard, whichever was created first.
-- =====================================================================

ALTER TABLE dispatch
    ADD COLUMN shade_override_reason text
        CHECK (shade_override_reason IS NULL OR length(trim(shade_override_reason)) > 0);

CREATE FUNCTION guard_dispatch_shade() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_override text;
    v_code     text;
    v_batches  text;
BEGIN
    SELECT d.shade_override_reason, d.code INTO v_override, v_code FROM dispatch d WHERE d.id = NEW.dispatch_id;
    IF v_override IS NOT NULL THEN
        RETURN NEW;
    END IF;

    -- the dye batch (producing run) of this roll and of every roll already on the dispatch
    SELECT string_agg(DISTINCT r.code, ', ' ORDER BY r.code) INTO v_batches
      FROM (SELECT NEW.lot_id AS lot_id
            UNION
            SELECT dl.lot_id FROM dispatch_line dl WHERE dl.dispatch_id = NEW.dispatch_id) x
      JOIN lot l          ON l.id = x.lot_id
      JOIN process_run r  ON r.id = l.produced_by_run_id;

    IF v_batches LIKE '%,%' THEN
        RAISE EXCEPTION 'dispatch % mixes dye batches %', v_code, v_batches
            USING ERRCODE = 'LL006',
                  DETAIL  = v_batches,
                  HINT    = 'Ship one dye batch per dispatch, or record a shade override reason (e.g. buyer approval).';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER dispatch_line_shade_guard
    BEFORE INSERT ON dispatch_line
    FOR EACH ROW EXECUTE FUNCTION guard_dispatch_shade();
