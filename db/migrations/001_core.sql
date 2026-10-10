-- =====================================================================
-- LoomLedger · 001 · Core schema
-- Two primitives: the LEDGER (stock_move) and the FAMILY TREE (lot_lineage).
-- Everything else (stock, cost, status, recall, impact) is derived.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- exclusion constraints on (id =, range &&)
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- password hashing for seeded users

-- The mill runs on IST: every new session renders timestamps in mill time (storage stays UTC).
DO $$ BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'Asia/Kolkata');
END $$;

-- ---------- Enumerations -------------------------------------------------
CREATE TYPE party_kind     AS ENUM ('buyer', 'supplier');
CREATE TYPE uom            AS ENUM ('kg', 'm');
CREATE TYPE product_kind   AS ENUM ('yarn', 'greige', 'finished');
CREATE TYPE location_kind  AS ENUM ('internal', 'supplier', 'customer', 'production', 'scrap', 'quarantine');
CREATE TYPE machine_stage  AS ENUM ('spinning', 'weaving', 'dyeing', 'finishing');
CREATE TYPE machine_state  AS ENUM ('running', 'idle', 'breakdown', 'changeover');
CREATE TYPE lot_status     AS ENUM ('active', 'wip', 'consumed', 'dispatched', 'quarantined', 'recalled');
CREATE TYPE move_kind      AS ENUM ('receipt', 'issue', 'production', 'consumption', 'scrap',
                                    'transfer', 'dispatch', 'quarantine', 'supplier_return');
CREATE TYPE qc_result      AS ENUM ('pass', 'rework', 'reject');
CREATE TYPE user_role      AS ENUM ('owner', 'store', 'floor_supervisor', 'qc', 'accounts');
CREATE TYPE order_status   AS ENUM ('confirmed', 'in_production', 'partially_dispatched', 'dispatched', 'cancelled');

-- ---------- Masters ------------------------------------------------------
CREATE TABLE app_user (
    id            bigserial PRIMARY KEY,
    email         text        NOT NULL UNIQUE CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    full_name     text        NOT NULL CHECK (length(trim(full_name)) > 0),
    role          user_role   NOT NULL,
    password_hash text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE party (
    id         bigserial PRIMARY KEY,
    code       text       NOT NULL UNIQUE,
    name       text       NOT NULL CHECK (length(trim(name)) > 0),
    kind       party_kind NOT NULL,
    phone      text,
    email      text
);

CREATE TABLE product (
    id          bigserial PRIMARY KEY,
    code        text         NOT NULL UNIQUE,
    name        text         NOT NULL,
    kind        product_kind NOT NULL,
    uom         uom          NOT NULL,
    gsm         integer      CHECK (gsm > 0),            -- grams per square metre
    width_m     numeric(4,2) CHECK (width_m > 0),
    colour      text,
    yarn_count  text,
    UNIQUE (id, kind),                                    -- target for composite FKs
    -- yarn is weighed, fabric is measured; fabric needs GSM + width for kg<->m conversion
    CHECK ( (kind = 'yarn' AND uom = 'kg' AND gsm IS NULL AND width_m IS NULL)
         OR (kind <> 'yarn' AND uom = 'm' AND gsm IS NOT NULL AND width_m IS NOT NULL) )
);

CREATE TABLE location (
    id    bigserial PRIMARY KEY,
    code  text          NOT NULL UNIQUE,
    name  text          NOT NULL,
    kind  location_kind NOT NULL
);

CREATE TABLE shift (
    id        smallserial PRIMARY KEY,
    code      text NOT NULL UNIQUE,
    name      text NOT NULL,
    starts_at time NOT NULL,
    ends_at   time NOT NULL
);

CREATE TABLE worker (
    id                bigserial PRIMARY KEY,
    code              text          NOT NULL UNIQUE,
    full_name         text          NOT NULL,
    skill             machine_stage,
    hourly_wage       numeric(10,2) NOT NULL CHECK (hourly_wage > 0),
    piece_rate_per_m  numeric(10,2) CHECK (piece_rate_per_m >= 0),
    active            boolean       NOT NULL DEFAULT true
);

CREATE TABLE machine (
    id                    bigserial PRIMARY KEY,
    code                  text          NOT NULL UNIQUE,
    name                  text          NOT NULL,
    stage                 machine_stage NOT NULL,
    rate_per_hour         numeric(10,2) NOT NULL CHECK (rate_per_hour >= 0),   -- running cost
    rated_output_per_hour numeric(10,2) CHECK (rated_output_per_hour > 0),
    active                boolean       NOT NULL DEFAULT true,
    UNIQUE (id, stage)                                                          -- target for composite FK
);

-- Planning parameter: how many metres/day a stage can deliver for a product.
-- The bottleneck (min across stages) drives delay estimates.
CREATE TABLE stage_capacity (
    product_id     bigint        NOT NULL,
    product_kind   product_kind  NOT NULL DEFAULT 'finished' CHECK (product_kind = 'finished'),
    stage          machine_stage NOT NULL,
    meters_per_day numeric(10,2) NOT NULL CHECK (meters_per_day > 0),
    PRIMARY KEY (product_id, stage),
    FOREIGN KEY (product_id, product_kind) REFERENCES product (id, kind)
);

-- ---------- Purchasing ---------------------------------------------------
CREATE TABLE goods_receipt (
    id          bigserial PRIMARY KEY,
    code        text        NOT NULL UNIQUE,
    supplier_id bigint      NOT NULL REFERENCES party (id),
    received_at timestamptz NOT NULL,
    vehicle_no  text,
    challan_no  text,
    received_by bigint      REFERENCES app_user (id)
);

-- ---------- Sales --------------------------------------------------------
CREATE TABLE sales_order (
    id                   bigserial PRIMARY KEY,
    code                 text         NOT NULL UNIQUE,
    buyer_id             bigint       NOT NULL REFERENCES party (id),
    order_date           date         NOT NULL,
    promised_date        date         NOT NULL,
    revised_promise_date date,
    status               order_status NOT NULL DEFAULT 'confirmed',
    CHECK (promised_date >= order_date),
    CHECK (revised_promise_date IS NULL OR revised_promise_date >= promised_date)
);

CREATE TABLE order_line (
    id           bigserial PRIMARY KEY,
    order_id     bigint        NOT NULL REFERENCES sales_order (id) ON DELETE CASCADE,
    product_id   bigint        NOT NULL,
    product_kind product_kind  NOT NULL DEFAULT 'finished' CHECK (product_kind = 'finished'),
    qty_m        numeric(12,2) NOT NULL CHECK (qty_m > 0),
    unit_price   numeric(10,2) NOT NULL CHECK (unit_price >= 0),
    FOREIGN KEY (product_id, product_kind) REFERENCES product (id, kind)   -- only finished fabric can be sold
);

-- ---------- Production ---------------------------------------------------
CREATE TABLE process_run (
    id            bigserial PRIMARY KEY,
    code          text          NOT NULL UNIQUE,
    machine_id    bigint        NOT NULL,
    stage         machine_stage NOT NULL,
    shift_id      smallint      NOT NULL REFERENCES shift (id),
    operator_id   bigint        NOT NULL REFERENCES worker (id),
    started_at    timestamptz   NOT NULL,
    ended_at      timestamptz,                         -- NULL = still running (WIP)
    chemical_cost numeric(12,2) NOT NULL DEFAULT 0 CHECK (chemical_cost >= 0),
    notes         text,
    UNIQUE (id, stage),
    CHECK (ended_at IS NULL OR ended_at > started_at),
    -- a run's stage must be the machine's stage (no "dyeing" on a loom)
    FOREIGN KEY (machine_id, stage) REFERENCES machine (id, stage),
    -- a machine cannot run two jobs at the same time — enforced by PostgreSQL, not the UI
    CONSTRAINT no_machine_double_booking
        EXCLUDE USING gist (machine_id WITH =, tstzrange(started_at, ended_at, '[)') WITH &&)
);

-- A LOT is any identifiable physical unit: a yarn lot, a greige roll, a finished roll.
CREATE TABLE lot (
    id                 bigserial PRIMARY KEY,
    code               text          NOT NULL UNIQUE,
    kind               product_kind  NOT NULL,
    product_id         bigint        NOT NULL,
    qty                numeric(14,3) NOT NULL CHECK (qty > 0),   -- received kg / produced (or planned) m
    unit_cost          numeric(12,4) CHECK (unit_cost >= 0),     -- purchase price; yarn only
    goods_receipt_id   bigint        REFERENCES goods_receipt (id),
    produced_by_run_id bigint,
    produced_by_stage  machine_stage,
    status             lot_status    NOT NULL DEFAULT 'active',
    created_at         timestamptz   NOT NULL DEFAULT now(),
    FOREIGN KEY (product_id, kind)                     REFERENCES product (id, kind),
    FOREIGN KEY (produced_by_run_id, produced_by_stage) REFERENCES process_run (id, stage),
    -- yarn is bought (receipt + price); fabric is made (by the right kind of run)
    CHECK ( (kind = 'yarn'     AND goods_receipt_id IS NOT NULL AND unit_cost IS NOT NULL
                               AND produced_by_run_id IS NULL)
         OR (kind = 'greige'   AND produced_by_run_id IS NOT NULL AND produced_by_stage = 'weaving'
                               AND goods_receipt_id IS NULL AND unit_cost IS NULL)
         OR (kind = 'finished' AND produced_by_run_id IS NOT NULL AND produced_by_stage IN ('dyeing', 'finishing')
                               AND goods_receipt_id IS NULL AND unit_cost IS NULL) )
);

-- THE FAMILY TREE: which lots were consumed to make which lots, and how much.
CREATE TABLE lot_lineage (
    parent_lot_id bigint        NOT NULL REFERENCES lot (id),
    child_lot_id  bigint        NOT NULL REFERENCES lot (id),
    qty_consumed  numeric(14,3) NOT NULL CHECK (qty_consumed > 0),   -- in the PARENT's unit
    PRIMARY KEY (parent_lot_id, child_lot_id),
    CHECK (parent_lot_id <> child_lot_id)
);

-- A roll can be promised to at most one order line.
CREATE TABLE reservation (
    lot_id        bigint      PRIMARY KEY REFERENCES lot (id),
    order_line_id bigint      NOT NULL REFERENCES order_line (id) ON DELETE CASCADE,
    reserved_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------- Quality ------------------------------------------------------
CREATE TABLE qc_inspection (
    id             bigserial PRIMARY KEY,
    lot_id         bigint        NOT NULL REFERENCES lot (id),
    inspector_id   bigint        NOT NULL REFERENCES worker (id),
    inspected_at   timestamptz   NOT NULL,
    result         qc_result     NOT NULL,
    defect_type    text,
    defect_meters  numeric(10,2) CHECK (defect_meters >= 0),
    notes          text,
    CHECK ((result = 'pass') = (defect_type IS NULL))   -- a failure must say why; a pass must not
);

-- ---------- Dispatch & money --------------------------------------------
CREATE TABLE dispatch (
    id            bigserial PRIMARY KEY,
    code          text        NOT NULL UNIQUE,
    order_id      bigint      NOT NULL REFERENCES sales_order (id),
    vehicle_no    text,
    dispatched_at timestamptz NOT NULL
);

CREATE TABLE dispatch_line (
    dispatch_id bigint NOT NULL REFERENCES dispatch (id) ON DELETE CASCADE,
    lot_id      bigint NOT NULL REFERENCES lot (id),
    PRIMARY KEY (dispatch_id, lot_id),
    CONSTRAINT one_dispatch_per_roll UNIQUE (lot_id)       -- a roll can never ship twice
);

CREATE TABLE invoice (
    id          bigserial PRIMARY KEY,
    code        text          NOT NULL UNIQUE,
    order_id    bigint        NOT NULL REFERENCES sales_order (id),
    dispatch_id bigint        NOT NULL UNIQUE REFERENCES dispatch (id),   -- one invoice per dispatch
    amount      numeric(14,2) NOT NULL CHECK (amount >= 0),
    issued_at   timestamptz   NOT NULL
);

CREATE TABLE payment (
    id         bigserial PRIMARY KEY,
    invoice_id bigint        NOT NULL REFERENCES invoice (id),
    amount     numeric(14,2) NOT NULL CHECK (amount > 0),
    paid_at    timestamptz   NOT NULL,
    method     text          NOT NULL CHECK (method IN ('bank_transfer', 'cheque', 'upi', 'cash'))
);

-- ---------- Recall -------------------------------------------------------
CREATE TABLE recall (
    id           bigserial PRIMARY KEY,
    code         text        NOT NULL UNIQUE,
    root_lot_id  bigint      NOT NULL UNIQUE REFERENCES lot (id),   -- one recall per root lot (idempotent)
    reason       text        NOT NULL CHECK (length(trim(reason)) > 0),
    initiated_by bigint      REFERENCES app_user (id),
    initiated_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- THE LEDGER ---------------------------------------------------
-- Stock is never stored; it is the sum of moves. Rows are never updated or deleted (see 002).
CREATE TABLE stock_move (
    id               bigserial PRIMARY KEY,
    lot_id           bigint        NOT NULL REFERENCES lot (id),
    from_location_id bigint        NOT NULL REFERENCES location (id),
    to_location_id   bigint        NOT NULL REFERENCES location (id),
    qty              numeric(14,3) NOT NULL CHECK (qty > 0),
    kind             move_kind     NOT NULL,
    process_run_id   bigint        REFERENCES process_run (id),
    goods_receipt_id bigint        REFERENCES goods_receipt (id),
    dispatch_id      bigint        REFERENCES dispatch (id),
    recall_id        bigint        REFERENCES recall (id),
    idempotency_key  text          NOT NULL UNIQUE,      -- retries / double-clicks / offline sync never double-post
    note             text,
    created_by       bigint        REFERENCES app_user (id),
    created_at       timestamptz   NOT NULL DEFAULT now(),
    CHECK (from_location_id <> to_location_id)
);

-- ---------- Floor --------------------------------------------------------
CREATE TABLE machine_state_log (
    id         bigserial PRIMARY KEY,
    machine_id bigint        NOT NULL REFERENCES machine (id),
    state      machine_state NOT NULL,
    reason     text,
    started_at timestamptz   NOT NULL,
    ended_at   timestamptz,
    CHECK (ended_at IS NULL OR ended_at > started_at),
    CONSTRAINT no_overlapping_machine_states
        EXCLUDE USING gist (machine_id WITH =, tstzrange(started_at, ended_at, '[)') WITH &&)
);
CREATE UNIQUE INDEX one_open_state_per_machine ON machine_state_log (machine_id) WHERE ended_at IS NULL;

-- ---------- People -------------------------------------------------------
CREATE TABLE attendance (
    worker_id bigint   NOT NULL REFERENCES worker (id),
    work_date date     NOT NULL,
    shift_id  smallint NOT NULL REFERENCES shift (id),
    status    text     NOT NULL CHECK (status IN ('present', 'absent', 'half_day', 'leave')),
    PRIMARY KEY (worker_id, work_date)
);

-- ---------- Buyer portal -------------------------------------------------
CREATE TABLE order_event (
    id               bigserial PRIMARY KEY,
    order_id         bigint      NOT NULL REFERENCES sales_order (id) ON DELETE CASCADE,
    kind             text        NOT NULL,
    message          text        NOT NULL,
    visible_to_buyer boolean     NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE buyer_link (
    token      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),   -- unguessable, no login needed
    order_id   bigint      NOT NULL REFERENCES sales_order (id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- Audit --------------------------------------------------------
CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    table_name text        NOT NULL,
    row_id     bigint      NOT NULL,
    action     text        NOT NULL,
    old_data   jsonb,
    new_data   jsonb,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text        NOT NULL DEFAULT current_user
);

-- ---------- Indexes (chosen for the queries in 003–005) -------------------
CREATE INDEX stock_move_lot_idx          ON stock_move (lot_id);
CREATE INDEX stock_move_to_loc_time_idx  ON stock_move (to_location_id, created_at);
CREATE INDEX stock_move_from_loc_time_idx ON stock_move (from_location_id, created_at);
CREATE INDEX stock_move_run_idx          ON stock_move (process_run_id) WHERE process_run_id IS NOT NULL;
CREATE INDEX lot_lineage_child_idx       ON lot_lineage (child_lot_id);       -- walk UP the tree
-- (PK on lot_lineage leads with parent_lot_id, which serves walking DOWN the tree)
CREATE INDEX lot_produced_by_run_idx     ON lot (produced_by_run_id);
CREATE INDEX lot_held_idx                ON lot (status) WHERE status IN ('quarantined', 'recalled', 'wip');
CREATE INDEX qc_lot_latest_idx           ON qc_inspection (lot_id, inspected_at DESC);
CREATE INDEX reservation_line_idx        ON reservation (order_line_id);
CREATE INDEX order_line_order_idx        ON order_line (order_id);
CREATE INDEX machine_state_open_idx      ON machine_state_log (machine_id, started_at DESC);
CREATE INDEX order_event_order_idx       ON order_event (order_id, created_at);
