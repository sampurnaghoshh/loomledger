import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { ListQuery } from "@/api/types";

/**
 * List state (page, page_size, q, sort, filters) kept in the URL query, so a filtered page can be shared,
 * bookmarked and survives a refresh / the back button.
 *   const list = useListQuery(["page", "q", "sort", "status"]);
 *   api.lists.orders(list.query) ... list.set("status", "dispatched")   // any change except the page resets to page 1
 */
export function useListQuery(keys: string[]) {
  const [params, setParams] = useSearchParams();
  const signature = keys.map((k) => `${k}=${params.get(k) ?? ""}`).join("&");
  const query: ListQuery = useMemo(
    () => Object.fromEntries(keys.map((k) => [k, params.get(k) ?? undefined])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  );
  const set = useCallback(
    (key: string, value: string | undefined) =>
      setParams(
        (cur) => {
          const next = new URLSearchParams(cur);
          if (value === undefined || value === "") next.delete(key);
          else next.set(key, value);
          if (key !== "page") next.delete("page");
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  return { query, signature, set, page: Number(query.page) || 1 };
}
