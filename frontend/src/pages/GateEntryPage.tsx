// Gate entry: a yarn delivery arrives at the mill gate and is booked into the yarn store as a new lot.
// Pattern: pages/LoginPage.tsx (Field + inline validation + useAction + ErrorBanner). Store and owner only.
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Lock, Truck } from "lucide-react";
import { api } from "@/api/client";
import type { InventoryMasters, ReceiptRequest, ReceiptResponse } from "@/api/types";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Loadable, PageHeader, Select } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { getSession } from "@/lib/auth";
import { formatINR, formatQty, newIdempotencyKey } from "@/lib/format";

const ALLOWED_ROLES = ["owner", "store"];
const LOT_CODE = /^Y-\d{3,}$/;

type FieldName = "supplier_code" | "product_code" | "lot_code" | "kg" | "price_per_kg" | "vehicle_no" | "challan_no";
type Form = Record<FieldName, string>;
type Errors = Partial<Record<FieldName, string>>;

export default function GateEntryPage() {
  const role = getSession()?.user.role;
  return (
    <div className="grid gap-6">
      <PageHeader title="Gate Entry" subtitle="Book a yarn delivery into the yarn store" />
      {role && ALLOWED_ROLES.includes(role) ? <GateEntry /> : <NotAllowed />}
    </div>
  );
}

function NotAllowed() {
  return (
    <Card>
      <EmptyState
        title="Gate entry is for the store"
        body="Sign in as store@ or owner@ to receive yarn."
        action={<Lock className="size-5 text-muted" aria-hidden />}
      />
    </Card>
  );
}

function GateEntry() {
  const masters = useApi(() => api.inventory.masters(), []);
  const [done, setDone] = useState<{ receipt: ReceiptResponse; value: number; supplier: string } | null>(null);
  const [formKey, setFormKey] = useState(0);            // remounts the form: fresh fields + fresh idempotency key

  return (
    <Loadable state={masters}>
      {(m) =>
        m.suppliers.length === 0 || m.yarn_products.length === 0 ? (
          <Card>
            <EmptyState title="No suppliers or yarn products set up" body="Ask the owner to add them before receiving yarn." />
          </Card>
        ) : done ? (
          <Receipt
            {...done}
            onAnother={() => {
              setDone(null);
              setFormKey((k) => k + 1);
            }}
          />
        ) : (
          <ReceiptForm key={formKey} masters={m} onReceived={setDone} />
        )
      }
    </Loadable>
  );
}

// ---------------------------------------------------------------- form
function emptyForm(m: InventoryMasters): Form {
  return {
    supplier_code: "",
    product_code: m.yarn_products.length === 1 ? m.yarn_products[0].code : "",
    lot_code: "",
    kg: "",
    price_per_kg: "",
    vehicle_no: "",
    challan_no: "",
  };
}

function validate(f: Form): Errors {
  const e: Errors = {};
  if (!f.supplier_code) e.supplier_code = "Choose the supplier.";
  if (!f.product_code) e.product_code = "Choose the yarn.";
  if (!LOT_CODE.test(f.lot_code)) e.lot_code = "Use Y- followed by at least 3 digits.";
  const kg = Number(f.kg);
  if (!f.kg || !Number.isFinite(kg) || kg <= 0) e.kg = "Enter the weight in kg (more than 0).";
  const rate = Number(f.price_per_kg);
  if (!f.price_per_kg || !Number.isFinite(rate) || rate <= 0) e.price_per_kg = "Enter the rate per kg (more than 0).";
  if (f.vehicle_no.length > 40) e.vehicle_no = "At most 40 characters.";
  if (f.challan_no.length > 40) e.challan_no = "At most 40 characters.";
  return e;
}

function ReceiptForm({
  masters,
  onReceived,
}: {
  masters: InventoryMasters;
  onReceived: (r: { receipt: ReceiptResponse; value: number; supplier: string }) => void;
}) {
  const [form, setForm] = useState<Form>(() => emptyForm(masters));
  const [errors, setErrors] = useState<Errors>({});
  const [idempotencyKey] = useState(newIdempotencyKey);    // one per form: a double submit can't book twice
  const receive = useAction(api.inventory.receive);

  const set = (name: FieldName) => (value: string) => {
    setForm((f) => ({ ...f, [name]: value }));
    if (errors[name]) setErrors((e) => ({ ...e, [name]: undefined }));
  };

  const kg = Number(form.kg);
  const rate = Number(form.price_per_kg);
  const value = kg > 0 && rate > 0 ? kg * rate : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs = validate(form);
    setErrors(errs);
    if (Object.keys(errs).length) return;

    const req: ReceiptRequest = {
      supplier_code: form.supplier_code,
      product_code: form.product_code,
      lot_code: form.lot_code,
      kg,
      price_per_kg: rate,
      vehicle_no: form.vehicle_no.trim() || undefined,
      challan_no: form.challan_no.trim() || undefined,
      idempotency_key: idempotencyKey,
    };
    const res = await receive.run(req);
    if (res) {
      const supplier = masters.suppliers.find((s) => s.code === req.supplier_code)?.name ?? req.supplier_code;
      onReceived({ receipt: res, value: res.kg * rate, supplier });
    }
  }

  // put the API's field errors next to the inputs they belong to
  useEffect(() => {
    const fields = pickFields(receive.error?.fields);
    if (Object.keys(fields).length) setErrors((current) => ({ ...current, ...fields }));
  }, [receive.error]);

  const busy = receive.running;
  return (
    <Card title="Yarn receipt" subtitle="Creates the goods receipt, the yarn lot, and its first stock movement into the yarn store">
      <form onSubmit={submit} noValidate className="grid gap-4">
        <ErrorBanner error={receive.error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Supplier" error={errors.supplier_code}>
            <Select value={form.supplier_code} onChange={(e) => set("supplier_code")(e.target.value)} disabled={busy}
              aria-invalid={!!errors.supplier_code}>
              <option value="">Choose…</option>
              {masters.suppliers.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name} ({s.code})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Yarn" error={errors.product_code}>
            <Select value={form.product_code} onChange={(e) => set("product_code")(e.target.value)} disabled={busy}
              aria-invalid={!!errors.product_code}>
              {masters.yarn_products.length > 1 && <option value="">Choose…</option>}
              {masters.yarn_products.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name} ({p.code})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Lot code" error={errors.lot_code} hint="The supplier's lot number, e.g. Y- and 3+ digits">
            <Input value={form.lot_code} onChange={(e) => set("lot_code")(e.target.value.toUpperCase().trim())} disabled={busy}
              className="font-mono" autoComplete="off" spellCheck={false} aria-invalid={!!errors.lot_code} />
          </Field>
          <Field label="Weight (kg)" error={errors.kg}>
            <Input type="number" inputMode="decimal" min={0} step="0.001" value={form.kg}
              onChange={(e) => set("kg")(e.target.value)} disabled={busy} aria-invalid={!!errors.kg} />
          </Field>
          <Field label="Rate (₹ per kg)" error={errors.price_per_kg}>
            <Input type="number" inputMode="decimal" min={0} step="0.01" value={form.price_per_kg}
              onChange={(e) => set("price_per_kg")(e.target.value)} disabled={busy} aria-invalid={!!errors.price_per_kg} />
          </Field>
          <div className="flex items-end">
            <p className="num text-sm text-muted">
              Value of this receipt: <span className="font-semibold text-ink">{value == null ? "—" : formatINR(value)}</span>
            </p>
          </div>
          <Field label="Vehicle no. (optional)" error={errors.vehicle_no}>
            <Input value={form.vehicle_no} onChange={(e) => set("vehicle_no")(e.target.value.toUpperCase())} disabled={busy}
              autoComplete="off" aria-invalid={!!errors.vehicle_no} />
          </Field>
          <Field label="Challan no. (optional)" error={errors.challan_no}>
            <Input value={form.challan_no} onChange={(e) => set("challan_no")(e.target.value)} disabled={busy}
              autoComplete="off" aria-invalid={!!errors.challan_no} />
          </Field>
        </div>
        <div>
          <Button type="submit" loading={busy} icon={<Truck className="size-4" />}>
            Receive yarn
          </Button>
        </div>
      </form>
    </Card>
  );
}

const FIELD_NAMES: FieldName[] = ["supplier_code", "product_code", "lot_code", "kg", "price_per_kg", "vehicle_no", "challan_no"];

/** Keep only the API field errors that belong to one of this form's inputs. */
function pickFields(fields: Record<string, string> | undefined): Errors {
  const out: Errors = {};
  for (const name of FIELD_NAMES) if (fields?.[name]) out[name] = humanizeFieldError(fields[name]);
  return out;
}

function humanizeFieldError(msg: string): string {
  return msg.charAt(0).toUpperCase() + msg.slice(1) + (/[.!?]$/.test(msg) ? "" : ".");
}

// ---------------------------------------------------------------- success
function Receipt({
  receipt,
  value,
  supplier,
  onAnother,
}: {
  receipt: ReceiptResponse;
  value: number;
  supplier: string;
  onAnother: () => void;
}) {
  return (
    <Card>
      <div role="status" className="grid gap-4">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-ok" aria-hidden />
          <div>
            <p className="text-lg font-semibold text-ink">
              Received · <span className="whitespace-nowrap font-mono">{receipt.receipt_code}</span>
            </p>
            <p className="text-sm text-muted">The lot is in stock and can be issued to a loom.</p>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-muted">Lot</dt>
            <dd className="font-mono font-medium text-ink">{receipt.lot_code}</dd>
          </div>
          <div>
            <dt className="text-muted">Weight</dt>
            <dd className="num font-medium text-ink">{formatQty(receipt.kg, "kg")}</dd>
          </div>
          <div>
            <dt className="text-muted">Value</dt>
            <dd className="num font-medium text-ink">{formatINR(value)}</dd>
          </div>
          <div>
            <dt className="text-muted">Now in</dt>
            <dd className="font-mono font-medium text-ink">{receipt.location}</dd>
          </div>
          <div className="col-span-2 sm:col-span-4">
            <dt className="text-muted">Supplier</dt>
            <dd className="font-medium text-ink">{supplier}</dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onAnother}>Receive another</Button>
          <Link to="/inventory" className="inline-flex items-center rounded-md border border-line px-3 py-2 text-sm font-medium text-ink hover:bg-canvas">
            View stock
          </Link>
        </div>
      </div>
    </Card>
  );
}
