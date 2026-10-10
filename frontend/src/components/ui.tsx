// LoomLedger UI kit. Build every screen from these; don't hand-roll buttons, cards, tables or badges.
import { useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertTriangle, Loader2, X } from "lucide-react";
import type { ApiError } from "@/api/errors";
import type { Tone } from "@/lib/tones";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

const toneClasses: Record<Tone, string> = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  hold: "bg-hold-soft text-hold",
  brand: "bg-brand-soft text-brand",
  accent: "bg-accent-soft text-accent",
  idle: "bg-idle-soft text-idle",
};
const toneText: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  hold: "text-hold",
  brand: "text-brand",
  accent: "text-accent",
  idle: "text-ink",
};

// ---------------------------------------------------------------- Button
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
};
export function Button({ variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest }: ButtonProps) {
  const variants = {
    primary: "bg-brand text-white hover:bg-brand/90",
    secondary: "bg-surface text-ink border border-line hover:bg-canvas",
    danger: "bg-bad text-white hover:bg-bad/90",
    ghost: "text-muted hover:text-ink hover:bg-canvas",
  };
  const sizes = { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-sm" };
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- Card
export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cx("rounded-xl border border-line bg-surface shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-5" : undefined}>{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- Badge
export function Badge({ tone = "idle", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium", toneClasses[tone], className)}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- StatTile
export function StatTile({ label, value, hint, tone = "idle" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={cx("num mt-1 text-2xl font-semibold", toneText[tone])}>{value}</p>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- PageHeader
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- DataTable
export type Column<T> = {
  key: string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  render?: (row: T) => ReactNode;
  className?: string;
};
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyText = "Nothing here yet.",
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emptyText?: string;
  onRowClick?: (row: T) => void;
}) {
  if (rows.length === 0) return <EmptyState title={emptyText} />;
  const align = { left: "text-left", right: "text-right", center: "text-center" };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line">
            {columns.map((c) => (
              <th key={c.key} className={cx("px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted", align[c.align ?? "left"])}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cx("border-b border-line last:border-0", onRowClick && "cursor-pointer hover:bg-canvas")}
            >
              {columns.map((c) => (
                <td key={c.key} className={cx("num px-3 py-2.5", align[c.align ?? "left"], c.className)}>
                  {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- feedback
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <p className="font-medium text-ink">{title}</p>
      {body && <p className="max-w-sm text-sm text-muted">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorBanner({ error, onRetry }: { error: ApiError | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-bad/30 bg-bad-soft px-4 py-3 text-sm text-bad">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <div className="flex-1">
        <p className="font-medium">{error.message}</p>
        {error.hint && <p className="mt-0.5 text-bad/80">{error.hint}</p>}
      </div>
      {onRetry && (
        <button className="font-medium underline" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

/** Loading / error / data in one place:  <Loadable state={useApi(...)}>{(data) => ...}</Loadable> */
export function Loadable<T>({
  state,
  children,
}: {
  state: { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
}) {
  if (state.error) return <ErrorBanner error={state.error} onRetry={state.reload} />;
  if (state.loading && state.data == null) return <Spinner />;
  if (state.data == null) return null;
  return <>{children(state.data)}</>;
}

// ---------------------------------------------------------------- Modal
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" onClick={onClose}>
      {/* Capped at 85% of the viewport: header and footer stay put, only the body scrolls (keeps buttons visible on phones). */}
      <div
        role="dialog"
        aria-modal="true"
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl bg-surface shadow-xl supports-[height:1dvh]:max-h-[85dvh]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button aria-label="Close" className="text-muted hover:text-ink" onClick={onClose}>
            <X className="size-5" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- form fields
export function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-sm text-bad">{error}</span> : hint && <span className="mt-1 block text-sm text-muted">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20 aria-[invalid=true]:border-bad";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputClass, props.className)} />;
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputClass, "min-h-20", props.className)} />;
}
