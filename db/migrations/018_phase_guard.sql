-- =====================================================================
-- LoomLedger · 018 · The production order can't be skipped, and every refusal is written down
-- Order: yarn -> weaving -> greige store -> dyeing -> QC -> finished store -> dispatch.
--   LL013 PHASE_SKIPPED (DETAIL = the missing phase), checked where a phase is recorded:
--     lot_lineage   greige is woven FROM YARN; a finished roll is dyed FROM A GREIGE ROLL whose weaving run has
--                   ended (a roll still on the loom can't go into a vat; yarn can't be dyed directly)
--     qc_inspection QC inspects DYED rolls whose dyeing run has ended (not greige, not yarn, not a roll still in
--                   the vat)
--   dispatch before a QC pass already exists: LL004 (009).
-- validation_log: one row per write that a business rule refused. The API writes it on a separate autocommit
-- connection after the refused transaction has rolled back, so the record survives the rollback.
-- =====================================================================

CREATE FUNCTION guard_phase_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_parent lot%ROWTYPE;
    v_child  lot%ROWTYPE;
    v_woven  timestamptz;
BEGIN
    SELECT * INTO v_parent FROM lot WHERE id = NEW.parent_lot_id;
    SELECT * INTO v_child  FROM lot WHERE id = NEW.child_lot_id;
    IF v_child.kind = 'greige' AND v_parent.kind <> 'yarn' THEN
        RAISE EXCEPTION 'Weaving needs yarn: % is a % lot', v_parent.code, v_parent.kind
            USING ERRCODE = 'LL013', DETAIL = 'yarn', HINT = 'Greige rolls are woven from a yarn lot.';
    END IF;
    IF v_child.kind = 'finished' THEN
        IF v_parent.kind <> 'greige' THEN
            RAISE EXCEPTION 'Dyeing needs a woven greige roll: % is %, so weaving was skipped', v_parent.code, v_parent.kind
                USING ERRCODE = 'LL013', DETAIL = 'weaving', HINT = 'Weave it on a loom first, then dye the greige roll.';
        END IF;
        SELECT ended_at INTO v_woven FROM process_run WHERE id = v_parent.produced_by_run_id;
        IF v_woven IS NULL THEN
            RAISE EXCEPTION 'Dyeing % before it is off the loom: its weaving run has not finished', v_parent.code
                USING ERRCODE = 'LL013', DETAIL = 'weaving', HINT = 'Finish the weaving run (greige to store) first.';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER lot_lineage_phase
    BEFORE INSERT ON lot_lineage
    FOR EACH ROW EXECUTE FUNCTION guard_phase_lineage();

CREATE FUNCTION guard_phase_qc() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_lot lot%ROWTYPE;
    v_dyed timestamptz;
BEGIN
    SELECT * INTO v_lot FROM lot WHERE id = NEW.lot_id;
    IF v_lot.kind <> 'finished' THEN
        RAISE EXCEPTION 'QC inspects dyed rolls: % is %, so %', v_lot.code, v_lot.kind,
                        CASE v_lot.kind WHEN 'greige' THEN 'dyeing was skipped' ELSE 'weaving and dyeing were skipped' END
            USING ERRCODE = 'LL013', DETAIL = CASE v_lot.kind WHEN 'greige' THEN 'dyeing' ELSE 'weaving' END,
                  HINT = 'Dye the greige roll first; QC inspects the finished roll that comes out of the vat.';
    END IF;
    SELECT ended_at INTO v_dyed FROM process_run WHERE id = v_lot.produced_by_run_id;
    IF v_dyed IS NULL THEN
        RAISE EXCEPTION 'QC on % before it is out of the dye vat: its dyeing run has not finished', v_lot.code
            USING ERRCODE = 'LL013', DETAIL = 'dyeing', HINT = 'Finish the dyeing run first.';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER qc_inspection_phase
    BEFORE INSERT ON qc_inspection
    FOR EACH ROW EXECUTE FUNCTION guard_phase_qc();

-- ---------- what was refused, by whom, and why
CREATE TABLE validation_log (
    id            bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    user_id       bigint      REFERENCES app_user (id),
    user_email    text,
    role          text,
    method        text        NOT NULL,
    path          text        NOT NULL,
    status        int         NOT NULL CHECK (status BETWEEN 400 AND 499),
    error_code    text        NOT NULL,
    sqlstate      text,
    message       text        NOT NULL,
    input_summary jsonb                                   -- a short, redacted summary of the request body
);
CREATE INDEX validation_log_at_idx ON validation_log (at DESC);
