// Formatting rules for the whole app. Never format numbers or dates by hand in a page.

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });
const pct = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** ₹1,23,640 (Indian grouping, no paise) */
export const formatINR = (n: number | null | undefined) => (n == null ? "—" : inr.format(n));

/** 1,499.1 */
export const formatNumber = (n: number | null | undefined) => (n == null ? "—" : num.format(n));

/** 600 m · 142.8 kg */
export const formatQty = (n: number | null | undefined, uom: "m" | "kg") => (n == null ? "—" : `${num.format(n)} ${uom}`);

/** 37.5% */
export const formatPct = (n: number | null | undefined) => (n == null ? "—" : `${pct.format(n)}%`);

/** 9.4× */
export const formatLift = (n: number | null | undefined) => (n == null ? "—" : `${num.format(n)}×`);

/** 16 Oct 2026 (accepts "2026-10-16" or a full timestamp) */
export function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T00:00:00+05:30`) : new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

/** Oct 2026 (accepts "2026-10", "2026-10-16" or a full timestamp) */
export function formatMonth(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso.slice(0, 7)}-01T00:00:00+05:30` : iso);
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
}

/** 16 Oct, 09:12 (mill time) */
export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  });
}

/** "3h 20m" since a timestamp */
export function formatSince(iso: string | null | undefined) {
  if (!iso) return "—";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  const h = Math.floor(mins / 60);
  return h ? `${h}h ${mins % 60}m` : `${mins}m`;
}

/** colour_mismatch → Colour mismatch */
export const humanize = (s: string | null | undefined) =>
  s ? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—";

/** new random key for every write request (safe retries) */
export const newIdempotencyKey = () => crypto.randomUUID();
