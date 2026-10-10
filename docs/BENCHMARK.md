# LoomLedger · query benchmark

Measured with `EXPLAIN (ANALYZE, BUFFERS)` on the seeded demo database. **Every number below was measured by PostgreSQL in this run; nothing is rounded up, averaged into a new value, or extrapolated to other data sizes** (golden rule 9).

- **Run:** 2026-10-10T15:39:45+05:30 (IST) · commit `af1bf0f` · demo day 2026-10-10 · recall applied: no (fresh seed)
- **Method:** 5 warm-up runs, then 51 measured runs per query; PostgreSQL's own `Execution Time`. Median = the middle measured value (odd run count); p95 = nearest-rank. All runs in one `READ ONLY` transaction, rolled back at the end.
- **Reproduce:** `./scripts/reset_demo.sh && python -m scripts.benchmark`

## Results (ms)

| Query (screen) | min | median | p95 | max | planning (median) | shared buffers hit | read from disk |
|---|---:|---:|---:|---:|---:|---:|---:|
| `find_cause(R-1201, R-1202, R-1203)` (Trace · Find Cause) | 2.213 | 2.419 | 2.965 | 4.592 | 1.615 | 107 | 0 |
| `recall_scope(Y-112)` (Recall · rolls) | 0.576 | 0.609 | 0.720 | 1.052 | 1.059 | 239 | 0 |
| `recall_impact(Y-112)` (Recall · impact + money) | 2.580 | 2.686 | 3.009 | 3.556 | 3.275 | 1269 | 0 |
| `lot_ancestors(R-1201)` (Trace · genealogy (up)) | 0.082 | 0.085 | 0.108 | 0.178 | 0.167 | 6 | 0 |
| `stock_on_hand(as_of = receipt of Y-112)` (Inventory · time travel) | 0.144 | 0.150 | 0.200 | 0.222 | 0.278 | 69 | 0 |
| `mass_balance(Oct 2026)` (Month end · mass balance) | 0.177 | 0.185 | 0.213 | 0.236 | 0.444 | 82 | 0 |
| `buyer_order_status(SO-0412)` (Buyer phone · track page) | 1.876 | 1.927 | 2.116 | 2.204 | 0.147 | 483 | 0 |

PostgreSQL reports times in ms to 3 decimals; they are printed as reported.

## Index use (every scan executed, including inside the functions)

Seq Scans are flagged ⚠ only on tables with ≥ 1,000 rows.

| Query | scans | flagged |
|---|---|---|
| `find_cause(R-1201, R-1202, R-1203)` | Seq Scan on `lot` ×8<br>Seq Scan on `lot_lineage` ×2<br>Index Scan on `machine` via `machine_id_stage_key`<br>Seq Scan on `machine`<br>Index Scan on `process_run` via `process_run_id_stage_key` ×2<br>Seq Scan on `process_run` ×2<br>Seq Scan on `qc_inspection`<br>Index Scan on `shift` via `shift_pkey`<br>Seq Scan on `shift` | — |
| `recall_scope(Y-112)` | Index Only Scan on `dispatch_line` via `one_dispatch_per_roll`<br>Seq Scan on `dispatch_line`<br>Seq Scan on `lot`<br>Bitmap Heap Scan on `lot_lineage`<br>Seq Scan on `lot_lineage` ×3<br>Index Scan on `order_line` via `order_line_pkey`<br>Index Scan on `party` via `party_pkey`<br>Index Scan on `process_run` via `process_run_id_stage_key`<br>Seq Scan on `qc_inspection`<br>Index Scan on `reservation` via `reservation_pkey`<br>Index Scan on `sales_order` via `sales_order_pkey` | — |
| `recall_impact(Y-112)` | Index Only Scan on `dispatch_line` via `one_dispatch_per_roll` ×2<br>Seq Scan on `dispatch_line` ×2<br>Index Scan on `location` via `location_pkey` ×6<br>Bitmap Heap Scan on `lot` ×22<br>Index Scan on `lot` via `lot_pkey` ×38<br>Seq Scan on `lot` ×25<br>Bitmap Heap Scan on `lot_lineage` ×25<br>Seq Scan on `lot_lineage` ×6<br>Index Scan on `machine` via `machine_id_stage_key` ×22<br>Index Scan on `order_line` via `order_line_pkey` ×3<br>Index Only Scan on `party` via `party_pkey`<br>Index Scan on `party` via `party_pkey`<br>Index Scan on `process_run` via `process_run_id_stage_key` ×25<br>Index Scan on `product` via `product_id_kind_key`<br>Seq Scan on `qc_inspection` ×2<br>Index Scan on `reservation` via `reservation_pkey` ×3<br>Index Scan on `sales_order` via `sales_order_pkey` ×3<br>Seq Scan on `stage_capacity`<br>Bitmap Heap Scan on `stock_move` ×3<br>Index Scan on `worker` via `worker_pkey` ×22 | — |
| `lot_ancestors(R-1201)` | Bitmap Heap Scan on `lot_lineage`<br>Seq Scan on `lot_lineage` | — |
| `stock_on_hand(as_of = receipt of Y-112)` | Seq Scan on `location`<br>Index Scan on `lot` via `lot_pkey`<br>Index Scan on `product` via `product_id_kind_key`<br>Seq Scan on `stock_move` ×2 | — |
| `mass_balance(Oct 2026)` | Bitmap Heap Scan on `lot`<br>Index Scan on `lot` via `lot_pkey`<br>Index Only Scan on `machine` via `machine_id_stage_key`<br>Bitmap Heap Scan on `process_run`<br>Seq Scan on `product`<br>Bitmap Heap Scan on `stock_move` ×2 | — |
| `buyer_order_status(SO-0412)` | Index Scan on `buyer_link` via `buyer_link_pkey`<br>Index Only Scan on `dispatch_line` via `one_dispatch_per_roll` ×5<br>Index Scan on `lot` via `lot_pkey`<br>Seq Scan on `lot_lineage` ×5<br>Bitmap Heap Scan on `order_event`<br>Bitmap Heap Scan on `order_line` ×3<br>Index Scan on `party` via `party_pkey`<br>Index Scan on `process_run` via `process_run_id_stage_key`<br>Index Scan on `product` via `product_id_kind_key`<br>Seq Scan on `qc_inspection`<br>Index Scan on `reservation` via `reservation_line_idx`<br>Index Scan on `sales_order` via `sales_order_pkey` | — |

## Findings (from the measurements above)

- Slowest query at p95: `recall_impact(Y-112)` — 3.009 ms (median 2.686 ms).
- Most pages read from disk in any measured run: 0.
- No Seq Scan on a table with ≥ 1,000 rows. The largest table is `stock_move` (632 rows); at this size PostgreSQL's cost model prefers sequential scans and would not choose an added index, so **no index migration is proposed from this data.** Re-run after the data grows: the flag column above shows when that changes.

## Data size (exact row counts)

| table | rows |
|---|---:|
| `lot` | 241 |
| `lot_lineage` | 229 |
| `stock_move` | 632 |
| `process_run` | 137 |
| `qc_inspection` | 108 |
| `reservation` | 90 |
| `order_line` | 4 |
| `sales_order` | 4 |
| `dispatch` | 2 |
| `dispatch_line` | 42 |
| `machine_state_log` | 147 |
| `order_event` | 6 |
| `buyer_link` | 4 |

## Machine

- **os:** Windows 11 (10.0.26300)
- **cpu:** 12th Gen Intel(R) Core(TM) i7-1250U
- **logical_cpus:** 12
- **ram:** 15.7 GiB
- **python:** 3.12.4
- **postgres:** PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
- **pg shared_buffers:** 128MB
- **pg work_mem:** 4MB
- **pg effective_cache_size:** 4GB
- **pg jit:** on
- **pg server:** Docker container on this host (Docker VM: 12 CPUs, 7.6 GiB RAM)
