import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { PermissionsInfo } from "@/api/types";
import { getSession } from "@/lib/auth";

// What the signed-in user may do comes from the database (GET /api/auth/permissions, 017), never from a list in
// the UI. Fetched once per session token and shared by every component that asks.
let cache: { token: string; promise: Promise<PermissionsInfo>; value: PermissionsInfo | null } | null = null;

function load(token: string) {
  if (!cache || cache.token !== token) {
    const entry = { token, value: null as PermissionsInfo | null, promise: api.auth.permissions() };
    entry.promise.then((v) => (entry.value = v)).catch(() => (cache = null)); // a failure is retried next time
    cache = entry;
  }
  return cache;
}

/**
 *   const { can } = usePermissions();
 *   {can("recalls.apply") && <Button>Apply recall</Button>}
 * While loading (or if it fails) `can` says no: a hidden button is safer than one the API will refuse.
 */
export function usePermissions() {
  const token = getSession()?.token ?? "";
  const [info, setInfo] = useState<PermissionsInfo | null>(() => (token && cache?.token === token ? cache.value : null));
  useEffect(() => {
    if (!token) return;
    let live = true;
    const entry = load(token);
    entry.promise.then((v) => live && setInfo(v)).catch(() => live && setInfo(null));
    return () => {
      live = false;
    };
  }, [token]);
  const mine = new Set(info?.me.permissions ?? []);
  return { info, loading: !!token && !info, can: (permission: string) => mine.has(permission) };
}
