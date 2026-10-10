# LoomLedger — frontend context pack (paste this into ChatGPT / Claude / any LLM first)

You are helping build **LoomLedger**, a textile-factory system for a 24-hour hackathon (Odoo finals).
Factory: "Everest Textile Mills". Yarn (kg) is woven into greige rolls, dyed into finished rolls (50 m each), inspected (QC), and dispatched to buyers.
The demo story: QC rejects 3 rolls → *Find Cause* blames Yarn Lot Y-112 → *Recall* quarantines everything made from it → impact on orders/money → the buyer sees the new date.

## Stack (do not change)
React 19 + TypeScript 5 (strict) + Vite + **Tailwind CSS v4** + react-router-dom 7 + lucide-react icons + recharts (charts).
No other libraries. No CSS files per page. No `any`. Function components + hooks only.

## Where things are
- `frontend/src/pages/<Name>Page.tsx` — one file per screen, `export default function <Name>Page()`.
- `@/api/client` → `api` object. **The only way to get data.** Mock data is served automatically (real responses from our database).
- `@/api/types` → all response types. `@/api/errors` → `ApiError { code, message, status, hint?, fields? }`.
- `@/components/ui` → UI kit (below). `@/hooks/useApi` → `useApi`, `useAction`. `@/lib/format`, `@/lib/tones`.

## API functions (all return Promises; types in types.ts)
```
api.auth.login(email, password)                      → LoginResponse
api.floor.machines()                                  → MachineNow[]
api.floor.output(day?)                                → FloorOutput
api.floor.availability(from?, to?)                    → FloorAvailability
api.floor.setState(machineCode, state, reason?)       → { machine_code, state, started_at }
api.floor.subscribe(onEvent)                          → unsubscribe()   // live FloorEvent pushes
api.inventory.stock(asOfIso?)                         → StockSnapshot   // asOf = time travel
api.inventory.receive(ReceiptRequest)                 → ReceiptResponse
api.production.startWeaving(StartWeavingRequest)      → StartWeavingResponse   // Y-112 after recall → ApiError LOT_QUARANTINED
api.quality.queue()                                   → QualityQueueItem[]
api.quality.rejections()                              → Rejection[]
api.quality.inspect(InspectionRequest)                → InspectionResponse
api.trace.findCause(lotCodes)                         → FindCauseResponse
api.trace.ancestors(lotCodes) / descendants(lotCode)  → LotGraph {nodes, edges}
api.recalls.preview(lotCode) / apply(lotCode, reason) → RecallResponse
api.orders.list()                                     → OrderSummary[]
api.orders.track(token)                               → BuyerOrderStatus   // public page; bad token → ApiError NOT_FOUND
api.finance.massBalance(from?, to?)                   → MassBalance
api.finance.rollCosts(orderCode)                      → RollCost[]
```

## Data loading pattern
```tsx
const state = useApi(() => api.floor.machines(), []);
return <Loadable state={state}>{(machines) => <div>...</div>}</Loadable>;   // handles loading + error + retry
```
Writes:
```tsx
const inspect = useAction(api.quality.inspect);
const res = await inspect.run(req);          // undefined if it failed; inspect.error has the ApiError
<ErrorBanner error={inspect.error} />  <Button loading={inspect.running}>Save</Button>
```

## UI kit (`@/components/ui`) — use these, never hand-roll
```
<Button variant="primary|secondary|danger|ghost" size="sm|md" loading? icon? />
<Card title? subtitle? actions? padded?={true}>…</Card>
<Badge tone="ok|warn|bad|hold|brand|accent|idle">text</Badge>
<StatTile label value hint? tone? />
<PageHeader title subtitle? actions? />
<DataTable columns={[{key, header, align?, render?(row)}]} rows rowKey={(r)=>r.code} emptyText? onRowClick? />
<Loadable state={useApi(...)}>{(data) => …}</Loadable>
<Spinner label? />  <EmptyState title body? action? />  <ErrorBanner error onRetry? />
<Modal open onClose title footer?>…</Modal>
<Field label error? hint?><Input|Select|Textarea …/></Field>
```

## Helpers
`@/lib/format`: `formatINR(123640)` → "₹1,23,640" · `formatQty(600,'m')` · `formatPct(37.5)` · `formatLift(9.38)` → "9.4×" · `formatDate('2026-10-16')` → "16 Oct 2026" · `formatDateTime(iso)` · `formatSince(iso)` → "3h 20m" · `humanize('colour_mismatch')` · `newIdempotencyKey()`.
`@/lib/tones`: `machineStateTone[state]`, `custodyTone[custody]`, `custodyLabel[custody]`, `lotStatusTone[status]`, `verdictTone[v]`, `verdictLabel[v]` → pass the tone to `<Badge>` / `<StatTile>`.

## Design rules
- Colours ONLY via theme classes: `bg-canvas bg-surface text-ink text-muted border-line bg-brand text-brand bg-brand-soft text-accent bg-accent-soft text-ok bg-ok-soft text-warn bg-warn-soft text-bad bg-bad-soft text-hold bg-hold-soft text-idle bg-idle-soft`. Never hex, never `blue-500` etc.
- Layout: `<PageHeader/>` then `<div className="grid gap-6">…</div>`. Stat tiles: `grid grid-cols-2 gap-4 lg:grid-cols-4`. Cards for every section.
- Codes like R-1201 / Y-112 / SO-0412 in `font-mono`. Numbers in tables/tiles already get tabular figures.
- Must look right at 375 px and 1280 px wide. Use `flex-wrap`, `overflow-x-auto` for tables.
- Every view: loading, error, empty states. Every form: inline validation, disabled while saving, API error shown.
- Never hardcode demo numbers (37.5, 600, ₹1,23,640…) — always display what the API returns.

## When you answer
Return the **complete file** (with its path as the first line comment), ready to paste over the existing file. No partial snippets, no placeholders like "…rest unchanged". If you need something that doesn't exist in the kit/API above, say so instead of inventing it.
