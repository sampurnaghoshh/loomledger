import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  ClipboardCheck,
  Factory,
  GitBranch,
  LogOut,
  Menu,
  PackageSearch,
  ReceiptIndianRupee,
  ShieldAlert,
  Truck,
  X,
} from "lucide-react";
import { USE_MOCKS } from "@/api/client";
import { getSession, setSession } from "@/lib/auth";

// Navigation. Add a page here AND in App.tsx routes.
const NAV = [
  {
    section: "Operations",
    items: [
      { to: "/floor", label: "Floor Board", icon: Activity },
      { to: "/inventory", label: "Inventory", icon: PackageSearch },
      { to: "/gate", label: "Gate Entry", icon: Truck },
      { to: "/quality", label: "Quality", icon: ClipboardCheck },
    ],
  },
  {
    section: "Traceability",
    items: [
      { to: "/trace", label: "Find Cause", icon: GitBranch },
      { to: "/recall/Y-112", label: "Recall", icon: ShieldAlert },
    ],
  },
  {
    section: "Business",
    items: [
      { to: "/orders", label: "Orders", icon: Factory },
      { to: "/month-end", label: "Month-end", icon: ReceiptIndianRupee },
    ],
  },
];

export function AppShell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const user = getSession()?.user;

  const nav = (
    <nav className="flex flex-col gap-6 p-4">
      {NAV.map((group) => (
        <div key={group.section}>
          <p className="mb-2 px-3 text-xs font-medium uppercase tracking-wide text-white/50">{group.section}</p>
          <ul className="flex flex-col gap-1">
            {group.items.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      isActive ? "bg-white/15 text-white" : "text-white/70 hover:bg-white/10 hover:text-white"
                    }`
                  }
                >
                  <Icon className="size-4" />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-full">
      {/* desktop sidebar */}
      <aside className="hidden w-60 shrink-0 bg-brand lg:block">
        <Brand />
        {nav}
      </aside>

      {/* mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-ink/40" />
          <aside className="relative h-full w-64 bg-brand" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <button aria-label="Close menu" className="text-white" onClick={() => setOpen(false)}>
                <X className="size-5" />
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-line bg-surface px-4 lg:px-6">
          <div className="flex items-center gap-3">
            <button aria-label="Open menu" className="text-ink lg:hidden" onClick={() => setOpen(true)}>
              <Menu className="size-5" />
            </button>
            <span className="text-sm font-medium text-muted">Everest Textile Mills</span>
            {USE_MOCKS && (
              <span className="rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn">mock data</span>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-muted sm:inline">
              {user?.full_name} · {user?.role.replace("_", " ")}
            </span>
            <button
              className="flex items-center gap-1 text-muted hover:text-ink"
              onClick={() => {
                setSession(null);
                navigate("/login");
              }}
            >
              <LogOut className="size-4" /> Log out
            </button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 px-6">
      <div className="grid size-7 place-items-center rounded-md bg-white text-sm font-bold text-brand">L</div>
      <span className="font-semibold tracking-tight text-white">LoomLedger</span>
    </div>
  );
}
