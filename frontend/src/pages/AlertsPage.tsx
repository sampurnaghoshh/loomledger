// Owner alerts: the phone on the table. Arm once (browsers only allow sound + vibration after a tap), then it
// listens on WS /ws/alerts. PostgreSQL sends a recall alert at COMMIT (never for a rolled-back recall, once per
// recall) and a breakdown alert when a machine stops. Live only: nothing from before arming is shown.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BellRing, Radio, ShieldAlert, Wrench } from "lucide-react";
import { api } from "@/api/client";
import type { SocketStatus } from "@/api/floorSocket";
import type { BreakdownAlert, OwnerAlert, RecallAlert } from "@/api/types";
import { Button } from "@/components/ui";
import { getSession } from "@/lib/auth";
import { formatDate, formatDateTime, formatINR } from "@/lib/format";

const ALERT_ROLES = ["owner", "qc"];
type Received = { id: number; alert: OwnerAlert; acknowledged: boolean };

/** "3 rolls" */
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// ---------------------------------------------------------------- sound + vibration (no files, no network)
function beep(ctx: AudioContext | null, times: number) {
  if (!ctx) return;
  try {
    void ctx.resume();
    for (let i = 0; i < times; i++) {
      const start = ctx.currentTime + i * 0.25;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.3, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.2);
    }
  } catch {
    /* audio unavailable: the screen still shows the alert */
  }
}

function vibrate(pattern: number[]) {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* not supported (e.g. iOS Safari) */
  }
}

export default function AlertsPage() {
  const user = getSession()?.user;
  const allowed = !!user && ALERT_ROLES.includes(user.role);
  const [armed, setArmed] = useState(false);
  const [status, setStatus] = useState<SocketStatus | "connecting">("connecting");
  const [alerts, setAlerts] = useState<Received[]>([]);
  const audio = useRef<AudioContext | null>(null);
  const nextId = useRef(1);

  async function arm() {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      audio.current = Ctx ? new Ctx() : null;
    } catch {
      audio.current = null;
    }
    beep(audio.current, 1); // the tap unlocks audio; this short beep proves it works
    vibrate([80]);
    try {
      await (navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<unknown> } }).wakeLock?.request("screen");
    } catch {
      /* keep-awake not supported: the phone may dim */
    }
    setArmed(true);
  }

  useEffect(() => {
    if (!armed) return;
    return api.alerts.subscribe((alert) => {
      setAlerts((cur) => [{ id: nextId.current++, alert, acknowledged: false }, ...cur]);
      const critical = alert.kind === "recall";
      beep(audio.current, critical ? 3 : 1);
      vibrate(critical ? [400, 150, 400, 150, 400] : [250]);
    }, setStatus);
  }, [armed]);

  // Full screen until acknowledged: an unacknowledged recall first (a later breakdown must not cover it), else the newest.
  const open = alerts.find((a) => !a.acknowledged && a.alert.kind === "recall") ?? alerts.find((a) => !a.acknowledged);
  const acknowledge = (id: number) => setAlerts((cur) => cur.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));

  return (
    <div className="min-h-screen bg-canvas">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
        <p className="text-sm font-semibold text-ink">
          LoomLedger <span className="font-normal text-muted">· Owner alerts</span>
        </p>
        <Link to="/floor" className="text-sm font-medium text-brand underline">
          Open app
        </Link>
      </header>

      <main className="mx-auto grid max-w-xl gap-4 px-4 py-6">
        {!allowed ? (
          <p role="alert" className="rounded-xl border border-line bg-surface p-5 text-ink">
            Owner alerts are for the owner and QC. Sign in as <span className="font-mono">owner@</span> or{" "}
            <span className="font-mono">qc@</span> to listen.
          </p>
        ) : !armed ? (
          <section className="grid gap-4 text-center">
            <button
              type="button"
              onClick={() => void arm()}
              className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-2xl bg-brand px-6 text-surface shadow-sm active:opacity-90"
            >
              <BellRing className="size-12" aria-hidden />
              <span className="text-3xl font-bold">Arm alerts</span>
              <span className="text-sm opacity-90">Tap once so this phone may beep and vibrate</span>
            </button>
            <p className="text-sm text-muted">
              Alerts are live only: you will see recalls and breakdowns from the moment you arm, nothing from before.
            </p>
          </section>
        ) : (
          <Listening status={status} />
        )}

        {alerts.length > 0 && (
          <section className="grid gap-3" aria-label="Alerts, newest first">
            <h2 className="text-sm font-semibold text-muted">Alerts · newest first</h2>
            {alerts.map((a) => (
              <AlertCard key={a.id} alert={a.alert} compact />
            ))}
          </section>
        )}
      </main>

      {open && (
        <div
          role="alertdialog"
          aria-live="assertive"
          aria-label={open.alert.kind === "recall" ? "Critical quality recall" : "Machine breakdown"}
          className={`fixed inset-0 z-50 overflow-y-auto p-4 ${open.alert.kind === "recall" ? "bg-bad" : "bg-warn"} text-surface`}
        >
          <div className="mx-auto grid max-w-xl gap-5 py-4">
            <AlertCard alert={open.alert} />
            <Button variant="secondary" className="h-14 text-lg" onClick={() => acknowledge(open.id)}>
              Acknowledge
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Listening({ status }: { status: SocketStatus | "connecting" }) {
  const text: Record<typeof status, string> = {
    connecting: "Connecting…",
    open: "Listening…",
    reconnecting: "Connection lost · reconnecting…",
    unauthorized: "Your session has expired. Sign in again to keep listening.",
    forbidden: "This account may not listen to owner alerts.",
  };
  const live = status === "open";
  return (
    <section className="grid justify-items-center gap-3 rounded-2xl border border-line bg-surface px-6 py-12 text-center" aria-live="polite">
      <span className="relative flex size-16 items-center justify-center">
        {live && <span className="absolute inset-0 animate-ping rounded-full bg-ok-soft" aria-hidden />}
        <Radio className={`relative size-10 ${live ? "text-ok" : "text-muted"}`} aria-hidden />
      </span>
      <p className={`text-2xl font-semibold ${live ? "text-ink" : "text-muted"}`}>{text[status]}</p>
      <p className="text-sm text-muted">Recalls and machine breakdowns appear here the moment they happen. Nothing older is shown.</p>
      {status === "unauthorized" && (
        <Link to="/login" state={{ from: "/alerts" }} className="text-sm font-medium text-brand underline">
          Sign in
        </Link>
      )}
    </section>
  );
}

function AlertCard({ alert, compact }: { alert: OwnerAlert; compact?: boolean }) {
  return alert.kind === "recall" ? <RecallCard a={alert} compact={compact} /> : <BreakdownCard a={alert} compact={compact} />;
}

function RecallCard({ a, compact }: { a: RecallAlert; compact?: boolean }) {
  if (compact)
    return (
      <article className="flex items-start gap-3 rounded-xl border-2 border-bad bg-bad-soft p-4 text-bad">
        <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="min-w-0 text-sm">
          <p className="font-bold">
            Critical quality recall · <span className="font-mono">{a.root_lot_code}</span>
          </p>
          <p className="num text-ink">
            {count(a.rolls_total, "roll")} · {a.rolls_at_customer} at buyers · {formatINR(a.total_exposure)} exposure
          </p>
          <p className="text-muted">{formatDateTime(a.applied_at)}</p>
        </div>
      </article>
    );
  return (
    <article className="grid gap-4">
      <div>
        <p className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide opacity-90">
          <ShieldAlert className="size-5" aria-hidden /> {a.recall_code} · {formatDateTime(a.applied_at)}
        </p>
        <h1 className="mt-1 text-4xl font-extrabold leading-tight">
          CRITICAL QUALITY RECALL · <span className="whitespace-nowrap font-mono">{a.root_lot_code}</span>
        </h1>
        <p className="mt-1 text-sm opacity-90">{a.reason}</p>
      </div>

      <dl className="num grid grid-cols-2 gap-3">
        <Stat label="Rolls affected" value={a.rolls_total} hint={`${a.rolls_rejected} rejected · ${a.rolls_at_risk} at risk`} />
        <Stat label="Already at buyers" value={a.rolls_at_customer} hint={a.at_buyers.map((b) => `${b.buyer} (${b.rolls.join(", ")})`).join(" · ") || "none"} />
        <Stat label="Orders affected" value={a.orders_affected} hint={count(a.buyers_affected, "buyer")} />
        <Stat label="Delay" value={`+${a.delay_days}`} hint="working days, worst order" />
      </dl>

      {a.orders.length > 0 && (
        <ul className="grid gap-1 rounded-xl bg-surface/15 p-3 text-sm">
          {a.orders.map((o) => (
            <li key={o.order_code} className="num flex flex-wrap justify-between gap-x-3">
              <span>
                <span className="font-mono font-semibold">{o.order_code}</span> · {o.buyer}
              </span>
              <span>
                +{o.delay_days} → {formatDate(o.revised_promise_date)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="rounded-xl bg-surface p-4 text-ink">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">Total exposure</p>
        <p className="num text-4xl font-bold text-bad">{formatINR(a.total_exposure)}</p>
      </div>

      <p className="rounded-xl border-2 border-surface p-4 text-lg font-semibold">
        Action: quarantine remaining material and contact affected buyers
      </p>
      <Link to={`/recall/${encodeURIComponent(a.root_lot_code)}`} className="text-center text-sm font-medium underline">
        Open the recall
      </Link>
    </article>
  );
}

function BreakdownCard({ a, compact }: { a: BreakdownAlert; compact?: boolean }) {
  if (compact)
    return (
      <article className="flex items-start gap-3 rounded-xl border-2 border-warn bg-warn-soft p-4 text-warn">
        <Wrench className="mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="min-w-0 text-sm">
          <p className="font-bold">Breakdown · {a.machine_name}</p>
          <p className="text-ink">{a.reason ?? "No reason given"}</p>
          <p className="text-muted">{formatDateTime(a.started_at)}</p>
        </div>
      </article>
    );
  return (
    <article className="grid gap-3">
      <p className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide opacity-90">
        <Wrench className="size-5" aria-hidden /> Machine breakdown · {formatDateTime(a.started_at)}
      </p>
      <h1 className="text-4xl font-extrabold leading-tight">{a.machine_name} has stopped</h1>
      <p className="text-lg">{a.reason ?? "No reason given"}</p>
      <p className="font-mono text-sm opacity-90">{a.machine_code}</p>
    </article>
  );
}

function Stat({ label, value, hint }: { label: string; value: number | string; hint: string }) {
  return (
    <div className="rounded-xl bg-surface/15 p-3">
      <dt className="text-xs font-medium uppercase tracking-wide opacity-90">{label}</dt>
      <dd className="text-3xl font-bold">{value}</dd>
      <dd className="text-xs opacity-90 break-words">{hint}</dd>
    </div>
  );
}
