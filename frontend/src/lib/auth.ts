import type { User } from "@/api/types";

// Token lives in memory, mirrored to localStorage so a refresh keeps you logged in.
// Storage can throw (private mode, blocked storage) — the app must still work without it.
const KEY = "loomledger.session";

let session: { token: string; user: User } | null = load();

function load(): { token: string; user: User } | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as { token: string; user: User }) : null;
  } catch {
    return null;
  }
}

export function getSession() {
  return session;
}

export function setSession(next: { token: string; user: User } | null) {
  session = next;
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: in-memory session still works */
  }
}
