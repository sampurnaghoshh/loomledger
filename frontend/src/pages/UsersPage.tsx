// Users & roles (owner, permission users.manage): change a role, activate / deactivate. The database guards it:
// the last active owner can't be removed (LAST_OWNER) and nobody deactivates themselves (SELF_DEACTIVATION);
// every change is audited with the acting owner. A deactivated user can't sign in and their session stops working.
import { Lock } from "lucide-react";
import { api } from "@/api/client";
import type { Role, UserRow } from "@/api/types";
import { Badge, Button, Card, DataTable, EmptyState, ErrorBanner, ListToolbar, Loadable, PageHeader, Pager, type Column } from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { useListQuery } from "@/hooks/useListQuery";
import { usePermissions } from "@/hooks/usePermissions";
import { getSession } from "@/lib/auth";
import { formatDate, humanize } from "@/lib/format";

const ROLES: Role[] = ["owner", "store", "floor_supervisor", "qc", "accounts"];

export default function UsersPage() {
  const { can, loading } = usePermissions();
  if (loading) return null;
  if (!can("users.manage"))
    return (
      <Card>
        <EmptyState title="Users & roles is for the owner" body="Sign in as owner@ to manage users." action={<Lock className="size-5 text-muted" aria-hidden />} />
      </Card>
    );
  return <UsersList />;
}

function UsersList() {
  const list = useListQuery(["page", "q", "sort", "role", "active"]);
  const users = useApi(() => api.users.list(list.query), [list.signature]);
  const change = useAction((id: number, body: { role?: Role; active?: boolean }) => api.users.update(id, body));
  const me = getSession()?.user.email;

  async function apply(id: number, body: { role?: Role; active?: boolean }) {
    if (await change.run(id, body)) void users.reload();
  }

  const columns: Column<UserRow>[] = [
    { key: "email", header: "Email", sortKey: "email", render: (u) => <span className="font-mono">{u.email}</span> },
    { key: "full_name", header: "Name", sortKey: "full_name" },
    {
      key: "role",
      header: "Role",
      sortKey: "role",
      render: (u) => (
        <select
          aria-label={`Role of ${u.email}`}
          value={u.role}
          disabled={change.running}
          onChange={(e) => void apply(u.id, { role: e.target.value as Role })}
          className="rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {humanize(r)}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: "active",
      header: "Status",
      sortKey: "active",
      render: (u) => <Badge tone={u.active ? "ok" : "idle"}>{u.active ? "Active" : "Deactivated"}</Badge>,
    },
    { key: "created_at", header: "Since", sortKey: "created_at", render: (u) => formatDate(u.created_at) },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      render: (u) => (
        <Button
          size="sm"
          variant={u.active ? "secondary" : "primary"}
          disabled={change.running}
          onClick={() => void apply(u.id, { active: !u.active })}
          aria-label={`${u.active ? "Deactivate" : "Activate"} ${u.email}${u.email === me ? " (you)" : ""}`}
        >
          {u.active ? "Deactivate" : "Activate"}
        </Button>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Users & roles"
        subtitle="Who can sign in, and with which role. The database keeps at least one active owner and won't let you deactivate yourself."
      />
      {change.error && <ErrorBanner error={change.error} />}
      <Card padded={false}>
        <div className="border-b border-line p-4">
          <ListToolbar
            q={list.query.q ?? ""}
            onSearch={(q) => list.set("q", q)}
            placeholder="Search email or name"
            filters={[
              { key: "role", label: "Role", options: ROLES.map((r) => ({ value: r, label: humanize(r) })) },
              { key: "active", label: "Status", options: [{ value: "true", label: "Active" }, { value: "false", label: "Deactivated" }] },
            ]}
            values={list.query}
            onFilter={(k, v) => list.set(k, v)}
          />
        </div>
        <Loadable state={users}>
          {(page) => (
            <>
              <DataTable columns={columns} rows={page.items} rowKey={(u) => String(u.id)} sort={list.query.sort} onSort={(s) => list.set("sort", s)}
                emptyText="No users match." />
              <div className="border-t border-line p-4">
                <Pager page={page.page} pageSize={page.page_size} total={page.total} onPage={(p) => list.set("page", String(p))} />
              </div>
            </>
          )}
        </Loadable>
      </Card>
    </div>
  );
}
