// QR labels: a printable A4 sheet. Each label's QR opens that roll's passport (/roll/<code>) on a phone.
// Default rolls come from GET /api/rolls/labels (a yarn lot's family + one clean roll); any roll can be added.
// QR codes are generated in the browser (qrcode), never by a third-party service.
import { useEffect, useMemo, useState, type FormEvent } from "react";
import QRCode from "qrcode";
import { Plus, Printer, RotateCcw, X } from "lucide-react";
import { api } from "@/api/client";
import type { RollLabel } from "@/api/types";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Loadable, PageHeader } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { formatQty } from "@/lib/format";

const BASE_KEY = "loomledger.qrBase";
const ROLL_CODE = /^R-\d{3,}(-G)?$/;

type Printable = Pick<RollLabel, "code" | "product" | "qty_m">;

function readBase(): string {
  try {
    return localStorage.getItem(BASE_KEY) || window.location.origin;
  } catch {
    return window.location.origin;
  }
}

function saveBase(value: string) {
  try {
    if (value === window.location.origin) localStorage.removeItem(BASE_KEY);
    else localStorage.setItem(BASE_KEY, value);
  } catch {
    /* storage unavailable: the base still works for this visit */
  }
}

const validBase = (v: string) => /^https?:\/\/[^\s/]+(:\d+)?\/?$/.test(v.trim());
const passportUrl = (base: string, code: string) => `${base.trim().replace(/\/$/, "")}/roll/${encodeURIComponent(code)}`;

export default function QrLabelsPage() {
  const defaults = useApi(() => api.rolls.labels(), []);
  const [base, setBase] = useState(readBase);
  const [added, setAdded] = useState<Printable[]>([]);
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  const lookup = useAction(api.rolls.passport);
  const baseOk = validBase(base);

  function changeBase(value: string) {
    setBase(value);
    if (validBase(value)) saveBase(value.trim());
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    const c = code.trim().toUpperCase();
    if (!ROLL_CODE.test(c)) return setCodeError("Enter a roll code like R-1204 or R-1212-G.");
    setCodeError(null);
    const p = await lookup.run(c); // the passport proves the roll exists and gives its product + metres
    if (!p) return;
    setAdded((cur) => (cur.some((r) => r.code === p.code) ? cur : [...cur, { code: p.code, product: p.product, qty_m: p.qty_m }]));
    setRemoved((cur) => {
      const next = new Set(cur);
      next.delete(p.code);
      return next;
    });
    setCode("");
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      {/* Print: only the sheet, 3 labels per row on A4 */}
      <style>{`
        @page { size: A4; margin: 10mm; }
        @media print {
          html, body, body * { background: transparent !important; }
          body * { visibility: hidden !important; }
          .qr-sheet, .qr-sheet * { visibility: visible !important; }
          .qr-sheet { position: absolute; inset: 0 auto auto 0; width: 100%; display: grid !important;
                      grid-template-columns: repeat(3, minmax(0, 1fr)) !important; gap: 4mm !important; }
          .qr-label { break-inside: avoid; box-shadow: none !important; }
        }
      `}</style>

      <div className="print:hidden">
        <PageHeader
          title="QR labels"
          subtitle="Print, stick on the rolls, scan with a phone: each code opens that roll's passport."
          actions={
            <Button icon={<Printer className="size-4" />} onClick={() => window.print()} disabled={!baseOk}>
              Print labels
            </Button>
          }
        />
      </div>

      <Card className="print:hidden">
        <div className="grid gap-4 lg:grid-cols-2">
          <Field
            label="QR link base"
            hint="Phones must reach this address, e.g. your laptop's hotspot IP: http://192.168.137.1:5173. Remembered on this browser."
            error={baseOk ? undefined : "Enter an address like http://192.168.137.1:5173"}
          >
            <div className="flex gap-2">
              <Input value={base} onChange={(e) => changeBase(e.target.value)} aria-invalid={!baseOk} inputMode="url" autoComplete="off" spellCheck={false} />
              <Button variant="secondary" icon={<RotateCcw className="size-4" />} onClick={() => changeBase(window.location.origin)} aria-label="Reset to this page's address">
                Reset
              </Button>
            </div>
          </Field>
          <form onSubmit={add} noValidate>
            <Field label="Add a roll" error={codeError ?? undefined} hint="Finished roll (R-1204) or a roll on the loom (R-1212-G).">
              <div className="flex gap-2">
                <Input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  aria-invalid={!!codeError}
                  placeholder="R-1204"
                  className="font-mono"
                  autoComplete="off"
                  disabled={lookup.running}
                />
                <Button type="submit" variant="secondary" loading={lookup.running} icon={<Plus className="size-4" />}>
                  Add
                </Button>
              </div>
            </Field>
            {lookup.error && (
              <div className="mt-2">
                <ErrorBanner error={lookup.error} />
              </div>
            )}
          </form>
        </div>
      </Card>

      <Loadable state={defaults}>
        {(data) => {
          const seen = new Set<string>();
          const labels = [...data.rolls, ...added].filter((r) => !removed.has(r.code) && !seen.has(r.code) && seen.add(r.code));
          return labels.length === 0 ? (
            <Card className="print:hidden">
              <EmptyState title="No labels" body="Add a roll code above." />
            </Card>
          ) : (
            <>
              <p className="text-sm text-muted print:hidden">
                {labels.length} labels
                {data.root && (
                  <>
                    {" "}· the rolls made from <span className="font-mono">{data.root}</span> (latest QC rejection) and one roll from elsewhere
                  </>
                )}
              </p>
              <div className="qr-sheet grid grid-cols-2 gap-3 sm:grid-cols-3">
                {labels.map((r) => (
                  <QrLabel
                    key={r.code}
                    roll={r}
                    url={baseOk ? passportUrl(base, r.code) : null}
                    onRemove={() => setRemoved((cur) => new Set(cur).add(r.code))}
                  />
                ))}
              </div>
            </>
          );
        }}
      </Loadable>
    </div>
  );
}

function QrLabel({ roll, url, onRemove }: { roll: Printable; url: string | null; onRemove: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    if (!url) return setSrc(null);
    QRCode.toDataURL(url, { margin: 1, width: 240, errorCorrectionLevel: "M" })
      .then((data) => live && setSrc(data))
      .catch(() => live && setSrc(null));
    return () => {
      live = false;
    };
  }, [url]);
  const alt = useMemo(() => `QR code for roll ${roll.code}`, [roll.code]);

  return (
    <div className="qr-label relative grid justify-items-center gap-1 rounded-lg border border-line bg-surface p-3 text-center shadow-sm">
      <button
        type="button"
        onClick={onRemove}
        className="absolute right-1.5 top-1.5 rounded p-1 text-muted hover:bg-canvas hover:text-ink print:hidden"
        aria-label={`Remove label ${roll.code}`}
      >
        <X className="size-4" />
      </button>
      {src ? <img src={src} alt={alt} className="aspect-square w-full max-w-36" /> : <div className="aspect-square w-full max-w-36 rounded bg-idle-soft" aria-hidden />}
      <p className="font-mono text-lg font-bold text-ink">{roll.code}</p>
      <p className="num text-xs text-muted">
        {roll.product} · {formatQty(roll.qty_m, "m")}
      </p>
    </div>
  );
}
