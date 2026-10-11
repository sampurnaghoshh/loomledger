// Record a QC pass for a roll by its code (e.g. the code on a scanned label). The database decides whether the roll
// may be inspected yet: a greige roll, or one still in the vat, is refused as PHASE_SKIPPED (migration 018) and the
// refusal is written to the validation log. Shown on the Quality page to QC / owner.
import { useState, type FormEvent } from "react";
import { ScanLine } from "lucide-react";
import { api } from "@/api/client";
import { Button, Card, ErrorBanner, Field, Input } from "@/components/ui";
import { useAction } from "@/hooks/useApi";

const ROLL_CODE = /^R-\d{3,}(-G)?$/;

export function InspectByCode({ onRecorded }: { onRecorded: () => void }) {
  const [code, setCode] = useState("");
  const [local, setLocal] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const inspect = useAction(api.quality.inspect);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const c = code.trim().toUpperCase();
    setDone(null);
    if (!ROLL_CODE.test(c)) return setLocal("Enter a roll code like R-1209 (or R-1213-G for a greige roll).");
    setLocal(null);
    const res = await inspect.run({ lot_code: c, result: "pass" });
    if (res) {
      setDone(`${res.lot_code} recorded as PASS.`);
      setCode("");
      onRecorded();
    }
  }

  return (
    <Card title="Inspect by roll code" subtitle="For a scanned label. The database refuses a roll that skipped a phase.">
      <form onSubmit={submit} noValidate className="grid gap-3">
        <Field label="Roll code" error={local ?? (inspect.error?.fields?.lot_code as string | undefined)}>
          <div className="flex gap-2">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="R-1209" className="font-mono"
              aria-invalid={!!local} autoComplete="off" disabled={inspect.running} />
            <Button type="submit" loading={inspect.running} icon={<ScanLine className="size-4" />}>
              Record pass
            </Button>
          </div>
        </Field>
        {inspect.error && inspect.error.code !== "VALIDATION_FAILED" && (
          <div role="alert" className="grid gap-1 rounded-lg border-2 border-bad bg-bad-soft p-3 text-sm text-bad">
            <p className="font-semibold">{inspect.error.code === "PHASE_SKIPPED" ? "Refused: a production phase was skipped" : "Refused"}</p>
            <p className="text-ink">{inspect.error.message}</p>
            {inspect.error.hint && <p>{inspect.error.hint}</p>}
            <p className="font-mono text-xs">
              {inspect.error.code}
              {inspect.error.sqlstate && <> · SQLSTATE {inspect.error.sqlstate}</>}
              {inspect.error.fields?.missing_phase && <> · missing phase: {inspect.error.fields.missing_phase}</>}
              {" "}· recorded in the validation log
            </p>
          </div>
        )}
        {inspect.error?.code === "VALIDATION_FAILED" && <ErrorBanner error={inspect.error} />}
        {done && <p role="status" className="text-sm text-ok">{done}</p>}
      </form>
    </Card>
  );
}
