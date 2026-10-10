// Placeholder used until the owner replaces the page. Shows what to build and the data it receives.
import type { ReactNode } from "react";
import { Card, Loadable, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";

export function TodoPage({
  title,
  owner,
  build,
  load,
}: {
  title: string;
  owner: string;
  build: ReactNode;
  load: () => Promise<unknown>;
}) {
  const state = useApi(load, []);
  return (
    <>
      <PageHeader title={title} subtitle={`Owner: ${owner} · see docs/TEAM_PLAN.md`} />
      <div className="grid gap-6">
        <Card title="To build">
          <div className="space-y-1 text-sm text-ink">{build}</div>
        </Card>
        <Card title="Data this page receives" subtitle="Live from the API client (mock or real)">
          <Loadable state={state}>
            {(data) => (
              <pre className="max-h-[480px] overflow-auto rounded-lg bg-canvas p-4 font-mono text-xs">
                {JSON.stringify(data, null, 2)}
              </pre>
            )}
          </Loadable>
        </Card>
      </div>
    </>
  );
}
