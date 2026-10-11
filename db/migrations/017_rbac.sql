-- =====================================================================
-- LoomLedger · 017 · Role-based access: the database is the source of truth
--   permission       : what can be done (code like 'quality.inspect'), with a description for the matrix page
--   role_permission  : role × permission (seeded from CLAUDE.md §6; the owner holds every permission explicitly)
--   app_user.active  : a deactivated user can't sign in, and tokens already issued stop working (the API re-reads
--                      the user on every request)
-- Rules (the API can't bypass them):
--   LL011  the last active owner can't be deactivated, demoted or deleted (someone must be able to manage users)
--   LL012  nobody can deactivate themselves
-- Every role/active change goes through set_user_access(), which records who did it in audit_log.
-- =====================================================================

ALTER TABLE app_user ADD COLUMN active boolean NOT NULL DEFAULT true;

CREATE TABLE permission (
    code        text PRIMARY KEY CHECK (code ~ '^[a-z_]+\.[a-z_]+$'),
    area        text NOT NULL,
    description text NOT NULL
);

CREATE TABLE role_permission (
    role       user_role NOT NULL,
    permission text      NOT NULL REFERENCES permission (code),
    PRIMARY KEY (role, permission)
);

INSERT INTO permission (code, area, description) VALUES
    ('floor.change_state',   'floor',      'Change a machine''s state (running, idle, breakdown, changeover)'),
    ('production.start_run', 'production', 'Start a weaving run (issue yarn to a loom)'),
    ('inventory.receive',    'inventory',  'Record yarn arriving at the gate (goods receipt)'),
    ('orders.dispatch',      'orders',     'Dispatch rolls to a buyer (creates the invoice)'),
    ('quality.inspect',      'quality',    'Record a QC inspection (pass / rework / reject)'),
    ('recalls.apply',        'recalls',    'Apply a recall (quarantine everything made from a lot)'),
    ('finance.access',       'finance',    'Month-end, P&L, mass balance, roll costs, invoices, payments'),
    ('workforce.register',   'workforce',  'Mark the attendance register and see the workers list'),
    ('workforce.wages',      'workforce',  'See the wage run'),
    ('alerts.listen',        'alerts',     'Receive live owner alerts (recalls, breakdowns) on a phone'),
    ('users.manage',         'admin',      'Change users'' roles and activate / deactivate them'),
    ('validation_log.view',  'admin',      'See the validation log (every write a business rule refused)');

INSERT INTO role_permission (role, permission)
SELECT 'owner', code FROM permission
UNION ALL VALUES
    ('store'::user_role,            'inventory.receive'),
    ('store',                       'orders.dispatch'),
    ('floor_supervisor',            'floor.change_state'),
    ('floor_supervisor',            'production.start_run'),
    ('floor_supervisor',            'workforce.register'),
    ('qc',                          'quality.inspect'),
    ('qc',                          'recalls.apply'),
    ('qc',                          'alerts.listen'),
    ('qc',                          'validation_log.view'),
    ('accounts',                    'finance.access'),
    ('accounts',                    'workforce.wages');

-- ---------- LL011: never leave the mill without an active owner
CREATE FUNCTION guard_last_owner() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.role = 'owner' AND OLD.active
       AND (TG_OP = 'DELETE' OR NOT (NEW.role = 'owner' AND NEW.active)) THEN
        PERFORM pg_advisory_xact_lock(hashtext('loomledger:active-owners'));   -- two owners demoting each other
        IF NOT EXISTS (SELECT 1 FROM app_user WHERE role = 'owner' AND active AND id <> OLD.id) THEN
            RAISE EXCEPTION '% is the last active owner', OLD.email
                USING ERRCODE = 'LL011',
                      HINT = 'Make another user an active owner first: someone must always be able to manage users.';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER app_user_last_owner
    BEFORE UPDATE OF role, active OR DELETE ON app_user
    FOR EACH ROW EXECUTE FUNCTION guard_last_owner();

-- ---------- the one way to change access: checks LL012, applies, audits with the acting user
CREATE FUNCTION set_user_access(p_actor bigint, p_user bigint, p_role user_role, p_active boolean)
RETURNS app_user
LANGUAGE plpgsql AS $$
DECLARE
    v_old   app_user%ROWTYPE;
    v_new   app_user%ROWTYPE;
    v_actor text;
BEGIN
    SELECT * INTO v_old FROM app_user WHERE id = p_user FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'user % does not exist', p_user USING ERRCODE = 'P0002';
    END IF;
    IF p_actor = p_user AND v_old.active AND NOT COALESCE(p_active, v_old.active) THEN
        RAISE EXCEPTION 'You can''t deactivate your own account'
            USING ERRCODE = 'LL012', HINT = 'Ask another owner to do it.';
    END IF;
    UPDATE app_user SET role = COALESCE(p_role, role), active = COALESCE(p_active, active)
     WHERE id = p_user RETURNING * INTO v_new;
    IF (v_old.role, v_old.active) IS DISTINCT FROM (v_new.role, v_new.active) THEN
        SELECT email INTO v_actor FROM app_user WHERE id = p_actor;
        INSERT INTO audit_log (table_name, row_id, action, old_data, new_data, changed_by)
        VALUES ('app_user', p_user, 'access',
                jsonb_build_object('email', v_old.email, 'role', v_old.role, 'active', v_old.active),
                jsonb_build_object('email', v_new.email, 'role', v_new.role, 'active', v_new.active),
                COALESCE(v_actor, current_user));
    END IF;
    RETURN v_new;
END $$;
