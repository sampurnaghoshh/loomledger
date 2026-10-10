// Workforce: the day's attendance register (one tap per worker, saved in one request) and the wage run for a month.
// Register: floor supervisor. Wages: accounts. The owner sees both.
import { useMemo, useState } from "react";
import { CheckCircle2, Lock, Users } from "lucide-react";
import { api } from "@/api/client";
import type { AttendanceRegister, AttendanceStatus, WageRow, WageRun } from "@/api/types";
import { Button, Card, DataTable, EmptyState, ErrorBanner, Field, Input, Loadable, PageHeader, Select, StatTile, type Column } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { getSession } from "@/lib/auth";
import { formatDate, formatINR, formatMonth, humanize, newIdempotencyKey } from "@/lib/format";
import type { Tone } from "@/lib/tones";

const REGISTER_ROLES = ["owner", "floor_supervisor"];
const WAGE_ROLES = ["owner", "accounts"];
const STATUSES: { value: AttendanceStatus; label: string; tone: Tone }[] = [
  { value: "present", label: "Present", tone: "ok" },
  { value: "half_day", label: "Half day", tone: "warn" },
  { value: "absent", label: "Absent", tone: "bad" },
  { value: "leave", label: "Leave", tone: "idle" },
];
// Literal class names so Tailwind generates them (tokens only).
const SELECTED: Record<Tone, string> = {
  ok: "border-ok bg-ok text-white",
  warn: "border-warn bg-warn text-white",
  bad: "border-bad bg-bad text-white",
  idle: "border-idle bg-idle text-white",
  hold: "border-hold bg-hold text-white",
  brand: "border-brand bg-brand text-white",
  accent: "border-accent bg-accent text-white",
};

function istToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date()); // YYYY-MM-DD
}

export default function WorkforcePage() {
  const role = getSession()?.user.role ?? "";
  const canRegister = REGISTER_ROLES.includes(role);
  const canWages = WAGE_ROLES.includes(role);
  const [tab, setTab] = useState<"register" | "wages">(canRegister ? "register" : "wages");

  return (
    <div className="grid gap-6">
      <PageHeader title="Workforce" subtitle="Attendance register and wages" />
      {!canRegister && !canWages ? (
        <Card>
          <EmptyState title="Workforce is for the floor supervisor and accounts"
            body="Sign in as floor@, accounts@ or owner@." action={<Lock className="size-5 text-muted" aria-hidden />} />
        </Card>
      ) : (
        <>
          {canRegister && canWages && (
            <div className="flex gap-2" role="tablist" aria-label="Workforce views">
              {(["register", "wages"] as const).map((t) => (
                <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`rounded-full border px-4 py-2 text-sm font-medium ${tab === t ? "border-brand bg-brand text-white" : "border-line bg-surface text-ink hover:bg-canvas"}`}>
                  {t === "register" ? "Attendance register" : "Wages"}
                </button>
              ))}
            </div>
          )}
          {tab === "register" && canRegister ? <RegisterView /> : <WagesView />}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- register
function RegisterView() {
  const [day, setDay] = useState(istToday);
  const register = useApi(() => api.workforce.register(day), [day]);
  return (
    <>
      <div className="max-w-xs">
        <Field label="Day" hint="Today or an earlier day">
          <Input type="date" value={day} max={istToday()} onChange={(e) => e.target.value && setDay(e.target.value)} />
        </Field>
      </div>
      <Loadable state={register}>
        {(r) =>
          r.workers.length === 0 ? (
            <Card><EmptyState title="No active workers" /></Card>
          ) : (
            <RegisterForm key={`${r.day}`} register={r} onSaved={() => void register.reload()} />
          )
        }
      </Loadable>
    </>
  );
}

function RegisterForm({ register, onSaved }: { register: AttendanceRegister; onSaved: () => void }) {
  const firstShift = register.shifts[0]?.code ?? "";
  const [shift, setShift] = useState(() => register.workers.find((w) => w.shift_code)?.shift_code ?? firstShift);
  const [marks, setMarks] = useState<Record<string, AttendanceStatus>>(() =>
    Object.fromEntries(register.workers.filter((w) => w.status).map((w) => [w.worker_code, w.status as AttendanceStatus])));
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);
  const [formError, setFormError] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const save = useAction(api.workforce.mark);

  const marked = Object.keys(marks).length;
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of Object.values(marks)) c[s] = (c[s] ?? 0) + 1;
    return c;
  }, [marks]);

  async function submit() {
    if (marked === 0) {
      setFormError("Mark at least one worker.");
      return;
    }
    setFormError(undefined);
    setSaved(undefined);
    const res = await save.run({
      day: register.day,
      shift_code: shift,
      marks: Object.entries(marks).map(([worker_code, status]) => ({ worker_code, status })),
      idempotency_key: idempotencyKey,
    });
    if (res) {
      setSaved(`Saved ${res.marked} worker${res.marked === 1 ? "" : "s"} for shift ${res.shift_code} on ${formatDate(res.day)}.`);
      setIdempotencyKey(newIdempotencyKey());      // the next save is a new submission
      onSaved();
    }
  }

  const busy = save.running;
  return (
    <Card
      title={`Register · ${formatDate(register.day)}`}
      subtitle={`${marked} of ${register.workers.length} marked · ${STATUSES.map((s) => `${counts[s.value] ?? 0} ${s.label.toLowerCase()}`).join(" · ")}`}
      actions={
        <Button variant="secondary" size="sm" disabled={busy}
          onClick={() => setMarks(Object.fromEntries(register.workers.map((w) => [w.worker_code, "present" as const])))}>
          Mark all present
        </Button>
      }
    >
      <div className="grid gap-4">
        {saved && (
          <p role="status" className="flex items-center gap-2 rounded-lg bg-ok-soft px-3 py-2 text-sm text-ok">
            <CheckCircle2 className="size-4" aria-hidden /> {saved}
          </p>
        )}
        <ErrorBanner error={save.error} />
        {formError && <p role="alert" className="text-sm text-bad">{formError}</p>}
        <div className="max-w-xs">
          <Field label="Shift">
            <Select value={shift} onChange={(e) => setShift(e.target.value)} disabled={busy}>
              {register.shifts.map((s) => (
                <option key={s.code} value={s.code}>{s.name} ({s.starts_at}–{s.ends_at})</option>
              ))}
            </Select>
          </Field>
        </div>
        <ul className="divide-y divide-line rounded-lg border border-line">
          {register.workers.map((w) => (
            <li key={w.worker_code} className="grid gap-2 px-3 py-3 sm:flex sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="font-medium text-ink">{w.full_name}</p>
                <p className="text-sm text-muted">
                  <span className="font-mono">{w.worker_code}</span> · {w.skill ? humanize(w.skill) : "Quality"}
                </p>
              </div>
              <div className="grid grid-cols-4 gap-1 sm:flex" role="radiogroup" aria-label={`Attendance for ${w.full_name}`}>
                {STATUSES.map((s) => {
                  const on = marks[w.worker_code] === s.value;
                  return (
                    <button key={s.value} type="button" role="radio" aria-checked={on} disabled={busy}
                      onClick={() => setMarks((m) => ({ ...m, [w.worker_code]: s.value }))}
                      className={`rounded-md border px-2 py-1.5 text-xs font-medium sm:px-3 ${on ? SELECTED[s.tone] : "border-line bg-surface text-ink hover:bg-canvas"}`}>
                      {s.label}
                    </button>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>
        <div>
          <Button onClick={() => void submit()} loading={busy} icon={<Users className="size-4" />}>
            Save register ({marked})
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- wages
function recentMonths(): string[] {
  const [y0, m0] = istToday().split("-").map(Number);
  return [0, 1, 2].map((back) => {
    const d = new Date(Date.UTC(y0, m0 - 1 - back, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}

function monthWindow(ym: string): { from: string; to: string } {
  const [y, m] = ym.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { from: `${ym}-01`, to: `${ym}-${String(last).padStart(2, "0")}` };
}

function WagesView() {
  const months = useMemo(recentMonths, []);
  const [month, setMonth] = useState(months[0]);
  const wages = useApi(() => {
    const w = monthWindow(month);
    return api.workforce.wages(w.from, w.to);
  }, [month]);

  return (
    <>
      <div className="max-w-xs">
        <Field label="Month">
          <Select value={month} onChange={(e) => setMonth(e.target.value)}>
            {months.map((m) => <option key={m} value={m}>{formatMonth(m)}</option>)}
          </Select>
        </Field>
      </div>
      <Loadable state={wages}>{(w) => <WageTable run={w} />}</Loadable>
    </>
  );
}

function WageTable({ run }: { run: WageRun }) {
  const columns: Column<WageRow>[] = [
    { key: "worker", header: "Worker", render: (r) => (
        <span className="whitespace-nowrap"><span className="font-medium">{r.full_name}</span> <span className="font-mono text-muted">{r.worker_code}</span></span>) },
    { key: "skill", header: "Skill", render: (r) => (r.skill ? humanize(r.skill) : "Quality") },
    { key: "rate", header: "₹ / hour", align: "right", render: (r) => formatINR(r.hourly_wage) },
    { key: "days", header: "Days", align: "right", render: (r) => r.days_worked },
    { key: "shifts", header: "Shifts", align: "right", render: (r) => r.shifts_worked },
    { key: "half", header: "Half days", align: "right", render: (r) => r.half_days },
    { key: "absent", header: "Absent", align: "right", render: (r) => r.absent_days },
    { key: "leave", header: "Leave", align: "right", render: (r) => r.leave_days },
    { key: "gross", header: "Gross", align: "right", render: (r) => <span className="font-semibold">{formatINR(r.gross_wage)}</span> },
  ];
  const t = run.totals;
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Workers" value={t.workers} />
        <StatTile label="Days worked" value={t.days_worked} />
        <StatTile label="Shifts worked" value={t.shifts_worked} />
        <StatTile label="Gross wages" value={formatINR(t.gross_wage)} tone="brand" />
      </div>
      <Card title={`Wages · ${formatDate(run.from)} – ${formatDate(run.to)}`}
        subtitle="A shift pays the hourly rate × the shift's length; a half day pays half; absence and leave are unpaid." padded={false}>
        <DataTable columns={columns} rows={run.workers} rowKey={(r) => r.worker_code} emptyText="No active workers." />
      </Card>
    </>
  );
}
