// Roles & permissions: the read-only matrix, straight from the database (017 role_permission).
import { Check } from "lucide-react";
import type { Role } from "@/api/types";
import { Card, PageHeader, Spinner } from "@/components/ui";
import { usePermissions } from "@/hooks/usePermissions";
import { humanize } from "@/lib/format";

export default function RolesPage() {
  const { info, loading } = usePermissions();
  if (loading || !info) return <Spinner />;
  const mine: Role = info.me.role;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Roles & permissions"
        subtitle="What each role may do. This is the table the API checks on every request; the screens hide what your role can't use."
      />
      <Card padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-xs font-medium uppercase tracking-wide text-muted">
                <th className="px-3 py-2 text-left">Permission</th>
                {info.roles.map((r) => (
                  <th key={r} scope="col" className={`px-3 py-2 text-center ${r === mine ? "text-brand" : ""}`}>
                    {humanize(r)}
                    {r === mine && <span className="block normal-case">(you)</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {info.permissions.map((p) => (
                <tr key={p.code} className="border-b border-line last:border-0">
                  <th scope="row" className="px-3 py-2.5 text-left font-normal">
                    <span className="block text-ink">{p.description}</span>
                    <span className="font-mono text-xs text-muted">{p.code}</span>
                  </th>
                  {info.roles.map((r) => (
                    <td key={r} className={`px-3 py-2.5 text-center ${r === mine ? "bg-brand-soft" : ""}`}>
                      {p.roles.includes(r) ? <Check className="mx-auto size-4 text-ok" aria-label="allowed" /> : <span className="text-muted" aria-label="not allowed">·</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-sm text-muted">Everyone signed in can see the floor, stock, quality lists, trace, recall preview, orders and records.</p>
    </div>
  );
}
