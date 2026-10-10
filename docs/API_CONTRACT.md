# LoomLedger API contract

**The JSON files in `docs/api-mocks/` are the contract.** They are real responses exported from the seeded database
(`python -m scripts.export_mocks`). The frontend builds against them in mock mode; every backend endpoint must return
exactly the same shape (same keys, same types, same nesting). If a shape must change: change the export script,
regenerate, update `frontend/src/api/types.ts`, and tell the team in the group chat.

- Base path `/api`. JSON in, JSON out. snake_case keys. Numbers are JSON numbers (₹ and kg are not strings).
- Dates `"2026-10-16"`; timestamps ISO-8601 with offset (`"2026-10-10T09:12:00+05:30"`).
- Auth: `Authorization: Bearer <token>` on everything except `POST /api/auth/login` and `GET /api/track/{token}`.
- Every write that creates stock movement takes an `idempotency_key` (UUID made once per form submit). Replaying the same key returns the original result with `200`, never a duplicate.

## Error envelope (every non-2xx)

```json
{ "error": { "code": "LOT_QUARANTINED", "message": "stock movement blocked: lot Y-112 is quarantined",
             "hint": "Quarantined stock can only go to quarantine, scrap, or back to the supplier.",
             "sqlstate": "LL001", "fields": null } }
```

| Source | HTTP | code |
|---|---|---|
| SQLSTATE `LL001` | 409 | `LOT_QUARANTINED` |
| SQLSTATE `LL002` | 422 | `INSUFFICIENT_STOCK` |
| SQLSTATE `LL003` | 405 | `LEDGER_IMMUTABLE` |
| SQLSTATE `LL004` (dispatch: roll's latest QC is not a pass) | 409 | `NOT_QC_PASSED` |
| SQLSTATE `LL005` (dispatch: roll not reserved for that order) | 422 | `NOT_IN_ORDER` |
| SQLSTATE `23P01` (exclusion) | 409 | `MACHINE_BUSY` |
| SQLSTATE `23505` on `one_dispatch_per_roll` | 409 | `ALREADY_DISPATCHED` |
| SQLSTATE `23505` on `idempotency_key` | 200 | (return the original result — services catch it with `app.errors.is_idempotency_replay`) |
| SQLSTATE `23505` on `idempotency_key`, not caught by the service | 409 | `DUPLICATE_REQUEST` |
| other `23xxx` / Pydantic validation | 422 | `VALIDATION_FAILED` + `fields: {name: message}` |
| SQLSTATE `22xxx` (bad enum text, out of range, invalid parameter e.g. `22023`) | 422 | `VALIDATION_FAILED` |
| SQLSTATE `P0002` (`lot % does not exist` in 004) | 404 | `NOT_FOUND` |
| SQLSTATE `40001` / `40P01` (serialization failure / deadlock) | 409 | `CONFLICT_RETRY` (safe to resubmit with the same idempotency key) |
| SQLSTATE `08xxx` / DB unreachable / pool timeout | 503 | `DB_UNAVAILABLE` |
| SQLSTATE `LL006` (dispatch mixes dye batches, no `shade_override_reason`) | 409 | `SHADE_MISMATCH` + `fields: {batches: "DB-08, DB-14"}` |
| bad login | 401 | `INVALID_CREDENTIALS` |
| missing/expired token | 401 | `UNAUTHENTICATED` |
| role not allowed | 403 | `FORBIDDEN` |
| unknown id/code/token | 404 | `NOT_FOUND` |
| anything else | 500 | `INTERNAL` (log with request id; never leak SQL to the client) |

All five keys are always present (`null` when not applicable). `sqlstate` is set only for errors raised by PostgreSQL.
Messages of our own `LL0xx` exceptions are passed through; every other DB error gets a fixed message (no SQL, no row data).
Implementation: `app/errors.py` (`map_db_error`). Examples: `error_lot_quarantined.json`, `error_not_found.json`.

## Endpoints

Owner = who builds the backend endpoint. Screen = who builds the page that uses it.

### Auth
| Method & path | Body / query | Response | Owner |
|---|---|---|---|
| `POST /api/auth/login` | `{email, password}` | `auth_login.json` | Sampurna |

Password check happens in SQL: `SELECT ... FROM app_user WHERE email = %s AND password_hash = crypt(%s, password_hash)`.

### Floor (Act 1)
| Method & path | Body / query | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/floor/machines` | – | `floor_machines.json` (`v_machine_now`) | Sampurna | Adithi |
| `GET /api/floor/output` | `?day=YYYY-MM-DD` (default: the latest working day in IST — a Sunday shows Saturday) | `floor_output.json` | Sampurna | Adithi |
| `GET /api/floor/availability` | `?from=&to=` (date or timestamp; naive = IST; default the 30 days before today 00:00 IST; `from` must be before `to`). `from`/`to` are returned with `+05:30` | `floor_availability.json` | Sampurna | Adithi |
| `POST /api/floor/machines/{code}/state` | `{state, reason?}` — closes the open state row, opens a new one, in one transaction (fires the `/ws/floor` events). Role `floor_supervisor` | `{machine_code, state, started_at}`; `404` unknown machine, `422` bad state | Sampurna | Adithi, simulator |
| `WS /ws/floor` | – | stream of `ws_floor_event.json` (relay of `LISTEN loomledger_floor`) | Sampurna | Adithi |

**`WS /ws/floor`** details (`app/realtime.py`):
- Auth: `ws://<host>/ws/floor?token=<login token>` (browsers can't set headers on a WebSocket). Missing/invalid/expired
  token → the server accepts, then closes with code **4401** (`unauthenticated`): send the user to login.
- Server → client only; each message is one JSON text frame shaped exactly like `ws_floor_event.json`. The payload is
  built by the database trigger (migration 006). A state change produces **two** events: the old row closing
  (`ended_at` set) and then the new open row (`ended_at: null`) — apply them in order; the open one is the machine's state now.
- No hello/snapshot message: on every (re)connect, call `GET /api/floor/machines` for the current board, then apply events.
  Events that happen while you're disconnected are not replayed.
- Close **1013** = client fell >100 messages behind; reconnect. Any other close: reconnect with backoff (e.g. 1 s → 30 s).
  `api.floor.subscribe(onEvent, onReconnect)` does this for you (`src/api/floorSocket.ts`: 1 → 15 s backoff, stops on 4401) and
  calls `onReconnect` after a reconnect so the page re-fetches what it missed.

### Inventory
| Method & path | Body / query | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/inventory/stock` | `?as_of=<ISO timestamp>` (omit = now) | `inventory_stock_now.json` / `inventory_stock_as_of.json` | Sampurna | Adithi |
| `GET /api/inventory/masters` | – (role `store`) | `inventory_masters.json`: `{suppliers: [{code, name}], yarn_products: [{code, name}]}` — the gate-entry form's choices | Sampurna | Sampurna |
| `POST /api/inventory/receipts` | `{supplier_code, lot_code (^Y-\d{3,}$), kg, price_per_kg, vehicle_no?, challan_no?, product_code?, idempotency_key}` → goods_receipt `GRN-<lot>` + yarn lot + receipt move SUPPLIERS → YARN-STORE. `product_code` omitted = the only yarn product. Role `store` | `201 {receipt_code, lot_code, kg, location}`; same `idempotency_key` again → `200` + the original body; `404` unknown supplier/product (`fields`); `422` lot code exists | Sampurna | Adithi |

### Production
| Method & path | Body | Response | Owner |
|---|---|---|---|
| `POST /api/production/weaving-runs` | `{machine_code, yarn_lot_code, product_code, meters_planned, order_code?, operator_code?, idempotency_key}` → run `WV-R-<n>` (shift = `shift_at(now())`), greige lot `R-<n>-G` `wip`, yarn issue YARN-STORE → PRODUCTION (kg = `weaving_yarn_issue_kg()` = m × width × GSM/1000 × 1.04), lineage, reservation. `product_code` is the **greige** product (e.g. GRG-TWL). `operator_code` omitted = first active weaver not on an open run. Role `floor_supervisor` | `201 {run_code, lot_code, yarn_issued_kg}`; replay → `200` original; `409 LOT_QUARANTINED` (this is the stage demo), `409 MACHINE_BUSY`, `422 INSUFFICIENT_STOCK`; `404` unknown machine/yarn/product/order/operator (`fields`); `422` not a weaving machine | Sampurna |
| `POST /api/production/weaving-runs/{run_code}/finish` | `{waste_kg, idempotency_key}` → end run (machine + labour hours now count in `lot_cost`), waste YARN PRODUCTION → SCRAP (if > 0), greige PRODUCTION → GREIGE-STORE, lot `active`. Role `floor_supervisor` | `{run_code, lot_code, meters}`; replay → same body; `404` unknown weaving run; `422` already finished; `409 LOT_QUARANTINED` if the roll was recalled while on the loom | Sampurna |
| `POST /api/production/dye-batches` | `{machine_code, greige_lot_codes[], chemical_cost, idempotency_key}` | `201 {batch_code}` | Sampurna (stretch) |
| `POST /api/production/dye-batches/{code}/finish` | `{idempotency_key}` → finished lots | `{batch_code, lot_codes[]}` | Sampurna (stretch) |

### Quality
| Method & path | Body / query | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/quality/queue` | – | `quality_queue.json` | Sampurna | Adithi |
| `GET /api/quality/rejections` | – | `quality_rejections.json` | Sampurna | Adithi |
| `GET /api/quality/latest-rejections` | – (any signed-in user) | `quality_latest_rejections.json`: `{day, rejections[]}` — the rejections of the latest day anything was rejected (mill time, so a Sunday still shows Saturday's); `day: null` when none | Sampurna | Adithi |
| `POST /api/quality/inspections` | `{lot_code, result, defect_type?, defect_meters?, notes?, inspector_code?, idempotency_key?}`; `defect_type` required unless `pass` (empty for `pass`); reject also moves the roll FG-STORE → REJECT-BAY in the same transaction. `inspector_code` omitted = first active QC inspector. Send `idempotency_key` (replays of a reject return the original). Role `qc` | `201 {inspection_id, lot_code, result}`; reject replay → `200`; `404` unknown finished roll/inspector; `422 INSUFFICIENT_STOCK` roll not in FG-STORE; `409 LOT_QUARANTINED` roll is quarantined | Sampurna | Adithi |

### Trace (Act 2)
| Method & path | Body | Response | Owner | Screen |
|---|---|---|---|---|
| `POST /api/trace/find-cause` | `{lot_codes: ["R-1201", ...]}` (1–500, distinct). Any signed-in user | `trace_find_cause.json` (`find_cause()`; ranked and judged by the DB); `404` unknown lot (`fields.lot_codes`) | Sampurna | Nooman |
| `POST /api/trace/graph` | `{lot_codes, direction: "up" \| "down"}` (default `up`): the lots + all ancestors (or descendants), nodes ordered by kind then code, edges only between listed nodes | `trace_graph_ancestors.json`; `404` unknown lot | Sampurna | Nooman |
| `GET /api/trace/lots/{code}/descendants` | – | `trace_graph_descendants.json`; `404` unknown lot | Sampurna | Nooman |

### Recall (Acts 3–4)
| Method & path | Body / query | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/recalls/preview` | `?lot_code=Y-112`. Any signed-in user | `recall_preview.json` (no `applied_at` key), or `recall_applied.json` once applied; `404` unknown lot | Sampurna | Nooman |
| `POST /api/recalls` | `{lot_code, reason (3–500 chars)}` → `apply_recall()`. Role `qc` | `201 recall_applied.json`; applying again → `200` with the **same** recall (code, time, numbers), nothing re-posted; `404` unknown lot | Sampurna | Nooman |

### Orders, dispatch, buyer portal
| Method & path | Body | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/orders` | – (any signed-in user; `tracking_token` = the order's newest unexpired link; `delay_days` = working days Mon–Sat from promised to revised via `working_days_between()`, 0 when on time) | `orders.json` (exported **after** the recall; before it `revised_promise_date` is null) | Sampurna | Dhruva |
| `POST /api/dispatches` | `{order_code, lot_codes[], vehicle_no, idempotency_key, shade_override_reason?}` → dispatch `DSP-<order>-<n>`, lines, each roll FG-STORE → CUSTOMERS, lots `dispatched`, invoice `INV-<order>-<n>` (Σ m × line price), order status, buyer update. Role `store`. Guards (DB): `409 NOT_QC_PASSED` (LL004), `422 NOT_IN_ORDER` (LL005), `409 LOT_QUARANTINED`, `422 INSUFFICIENT_STOCK` (not in FG-STORE), `409 ALREADY_DISPATCHED`. Shade Guard (migration 008): all rolls of **one dispatch** from one dye batch, else `409 SHADE_MISMATCH` with `fields.batches`, unless `shade_override_reason` (3–500 chars) is given — it is stored on the dispatch | `201 {dispatch_code, invoice_code, amount}`; replay → `200` original; `404` unknown order/roll | Sampurna | Dhruva (stretch) |
| `GET /api/track/{token}` | public, no login (`buyer_order_status(token)`) | `track_SO-0412_before.json` / `_after.json`; malformed, unknown and expired tokens all return the same `404 error_not_found.json` | Sampurna | Dhruva |

### Finance (month-end)
| Method & path | Query | Response | Owner | Screen |
|---|---|---|---|---|
| `GET /api/finance/mass-balance` | `?from=&to=` (default all time = `null`; date or timestamp, naive = IST; window = runs **started** in `[from, to)`; `by_machine` uses the same window, worst first, ties by machine code; empty window → zeros + `unaccounted_pct: null`; `first_run_at` = earliest weaving run in the window, null if none). Role `accounts` | `finance_mass_balance.json`; `422` bad window | Sampurna | Dhruva |
| `GET /api/finance/roll-costs` | `?order_code=SO-0412` (required) — every roll reserved for the order, `v_roll_cost` (material + machine + labour + chemicals) + custody. Role `accounts` | `finance_roll_costs_SO-0412.json` (exported after the recall; costs are the same before it); `404` unknown order, `422` missing `order_code` | Sampurna | Dhruva |

## Contract test (backend)

For every GET above: seed, call the endpoint, compare with the mock file. Ignore only wall-clock fields
(`applied_at`, `at` of events created during the test, `state_since` of rows the test changed). A red contract test means
the frontend will break when mocks are switched off.
