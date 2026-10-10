// Find Cause: walk the ancestry of the rejected rolls and rank every shared factor by how much it lifts the defect rate.
import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api } from "@/api/client";
import type { CauseFactor, LotGraph } from "@/api/types";
import { LotGraph as GenealogyGraph } from "@/components/LotGraph";
import { Badge, Button, Card, EmptyState, Loadable, PageHeader, StatTile } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatLift, formatPct, humanize } from "@/lib/format";
import { verdictLabel, verdictTone, type Tone } from "@/lib/tones";

/** "1 roll" / "3 rolls" */
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// Literal classes so Tailwind picks them up. Neutral verdicts still get a visible "through" bar.
const barFill: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  hold: "bg-hold",
  brand: "bg-brand",
  accent: "bg-accent",
  idle: "bg-brand",
};

function parseLots(raw: string | null): string[] {
  const lots = (raw ?? "")
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  return [...new Set(lots)];
}

/** Only for a yarn-lot factor: the yarn node whose code appears as a whole word in its label ("Yarn Lot Y-112" → Y-112). */
function rootYarnCode(top: CauseFactor | undefined, graph: LotGraph | null): string | null {
  if (!top || top.factor_kind !== "yarn_lot" || !graph) return null;
  const words = top.factor_label.split(/\s+/);
  return graph.nodes.find((n) => n.kind === "yarn" && words.includes(n.code))?.code ?? null;
}

/** Plain-English reason a coincidental factor is not the cause, built only from its own numbers. */
function whyCoincidental(f: CauseFactor): string {
  const through = formatPct(f.rate_through_pct);
  const outside = formatPct(f.rate_outside_pct);
  const comparison =
    f.lift != null && f.lift < 1
      ? `that is no higher than the ${outside} rate elsewhere`
      : `only ${formatLift(f.lift)} the ${outside} rate elsewhere`;
  return (
    `${f.factor_label}: ${f.rejected_through} of ${count(f.inspected_through, "roll")} through it ${f.rejected_through === 1 ? "was" : "were"} rejected (${through}), ` +
    `${comparison}. Rolls that never touched it fail at a similar rate, so it was on the path of the bad rolls without causing them.`
  );
}

export default function TracePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const lots = useMemo(() => parseLots(params.get("lots")), [params]);
  const lotsKey = lots.join(",");

  // No rolls picked: don't call the trace endpoints at all.
  const cause = useApi(() => (lots.length ? api.trace.findCause(lots) : Promise.resolve(null)), [lotsKey]);
  const graph = useApi(() => (lots.length ? api.trace.ancestors(lots) : Promise.resolve(null)), [lotsKey]);

  const top = cause.data?.factors[0];
  const rootCode = rootYarnCode(top, graph.data);

  if (lots.length === 0) return <PickRejectedRolls />;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Find Cause"
        subtitle="Walks the family tree of the selected rolls and compares defect rates through each shared factor against everything else."
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted">Selected rolls</span>
        {lots.map((code) => (
          <Link
            key={code}
            to={`/roll/${encodeURIComponent(code)}`}
            className="whitespace-nowrap rounded-full border border-line bg-surface px-2.5 py-0.5 font-mono text-sm text-ink hover:border-brand hover:text-brand"
            title="Open passport"
            aria-label={`Passport for ${code}`}
          >
            {code}
          </Link>
        ))}
      </div>

      <Loadable state={cause}>
        {(data) =>
          !data ? null : data.factors.length === 0 ? (
            <Card>
              <EmptyState title="No shared factors found" body="These rolls have no common yarn lot, machine or shift with inspection history to compare." />
            </Card>
          ) : (
            <>
              <Headline factor={data.factors[0]} rootCode={rootCode} onRecall={(code) => navigate(`/recall/${encodeURIComponent(code)}`)} />
              <FactorTable factors={data.factors} />
              <Coincidental factors={data.factors.filter((f) => f.verdict === "coincidental")} />
            </>
          )
        }
      </Loadable>

      <Card title="Genealogy" subtitle="Yarn lot → greige roll → finished roll, with machine and shift on each lot. Drag to pan, pinch or use the buttons to zoom.">
        <Loadable state={graph}>
          {(g) =>
            !g ? null : g.nodes.length === 0 ? (
              <EmptyState title="No ancestry recorded for these rolls" />
            ) : (
              <GenealogyGraph graph={g} colorBy="kind" highlight={lots} rootCause={rootCode ?? undefined} />
            )
          }
        </Loadable>
      </Card>
    </div>
  );
}

/** Find Cause needs rejected rolls: offer the QC rejections as a starting point. */
function PickRejectedRolls() {
  const navigate = useNavigate();
  const rejections = useApi(() => api.quality.rejections(), []);
  const go = (codes: string[]) => navigate(`/trace?${new URLSearchParams({ lots: codes.join(",") })}`);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader title="Find Cause" subtitle="Walks the family tree of rejected rolls and compares defect rates through every shared factor." />
      <Card>
        <EmptyState
          title="Pick the rejected rolls to investigate"
          body="Find Cause needs one or more rejected rolls. Trace one roll, or every roll with the same defect. Mixing unrelated defects skews the comparison."
        />
        <Loadable state={rejections}>
          {(rows) => {
            // Latest rejection per roll (rows are newest first), grouped by defect type, biggest group first.
            const latest = rows.filter((r, i) => rows.findIndex((x) => x.lot_code === r.lot_code) === i);
            if (latest.length === 0) return <EmptyState title="No rejected rolls yet" body="Rolls rejected at QC will appear here." />;
            const byDefect = new Map<string, typeof latest>();
            for (const r of latest) byDefect.set(r.defect_type, [...(byDefect.get(r.defect_type) ?? []), r]);
            const groups = [...byDefect].sort(
              ([a, x], [b, y]) => y.length - x.length || a.localeCompare(b),
            );
            return (
              <ul className="grid gap-3">
                {groups.map(([defect, items], gi) => {
                  const name = defect.replace(/_/g, " ");
                  return (
                    <li key={defect} className="grid gap-3 rounded-lg border border-line p-4 sm:flex sm:items-center sm:justify-between">
                      <div className="grid gap-2">
                        <p className="text-sm font-medium text-ink">
                          {humanize(defect)} <span className="font-normal text-muted">· {count(items.length, "roll")}</span>
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {items.map((r) => (
                            <Button key={r.lot_code} variant="secondary" size="sm" onClick={() => go([r.lot_code])}>
                              <span className="whitespace-nowrap font-mono">{r.lot_code}</span>
                            </Button>
                          ))}
                        </div>
                      </div>
                      <Button
                        variant={gi === 0 ? "primary" : "secondary"}
                        icon={<ArrowRight className="size-4" />}
                        onClick={() => go(items.map((r) => r.lot_code))}
                        className="shrink-0"
                      >
                        {items.length === 1 ? `Trace the ${name} roll` : `Trace the ${items.length} ${name} rolls`}
                      </Button>
                    </li>
                  );
                })}
              </ul>
            );
          }}
        </Loadable>
      </Card>
    </div>
  );
}

function Headline({ factor, rootCode, onRecall }: { factor: CauseFactor; rootCode: string | null; onRecall: (code: string) => void }) {
  const tone = verdictTone[factor.verdict];
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {factor.factor_label}
          <Badge tone={tone}>{verdictLabel[factor.verdict]}</Badge>
        </span>
      }
      subtitle={`Strongest candidate · covers ${factor.selected_covered} of ${count(factor.selected_total, "selected roll")}`}
    >
      <div className="grid gap-4">
        <p className="text-sm text-ink">
          Rolls made through <span className="font-medium">{factor.factor_label}</span> were rejected at{" "}
          <span className="num font-semibold">{formatPct(factor.rate_through_pct)}</span>, against{" "}
          <span className="num font-semibold">{formatPct(factor.rate_outside_pct)}</span> for everything else.
        </p>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Defect rate through it" value={formatPct(factor.rate_through_pct)} tone={tone} />
          <StatTile label="Defect rate elsewhere" value={formatPct(factor.rate_outside_pct)} />
          <StatTile label="Lift" value={formatLift(factor.lift)} tone={tone} />
          <StatTile label="Rejected / inspected" value={`${factor.rejected_through} / ${factor.inspected_through}`} />
        </div>
        {rootCode && (
          <div>
            <Button variant="danger" icon={<ArrowRight className="size-4" />} onClick={() => onRecall(rootCode)}>
              Recall <span className="whitespace-nowrap font-mono">{rootCode}</span>
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function FactorTable({ factors }: { factors: CauseFactor[] }) {
  const maxRate = Math.max(1, ...factors.flatMap((f) => [f.rate_through_pct ?? 0, f.rate_outside_pct ?? 0]));
  return (
    <Card title="Every shared factor, ranked" subtitle="Defect rate through each factor vs everywhere else" padded={false}>
      <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)_5rem_minmax(0,1.2fr)] gap-4 border-b border-line px-5 py-2 text-xs font-medium uppercase tracking-wide text-muted lg:grid">
        <span>Factor</span>
        <span>Defect rate</span>
        <span className="text-right">Lift</span>
        <span>Verdict</span>
      </div>
      <ol>
        {factors.map((f, i) => {
          const muted = f.verdict === "no_comparison";
          return (
            <li
              key={`${f.factor_kind}-${f.factor_label}`}
              className={`grid gap-3 border-b border-line px-5 py-4 last:border-0 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)_5rem_minmax(0,1.2fr)] lg:items-center lg:gap-4 ${muted ? "opacity-60" : ""}`}
            >
              <div className="min-w-0">
                <p className="font-medium text-ink">
                  <span className="num mr-2 text-muted">{i + 1}.</span>
                  {f.factor_label}
                </p>
                <p className="num mt-0.5 text-sm text-muted">
                  {humanize(f.factor_kind)} · covers {f.selected_covered}/{f.selected_total} · {f.rejected_through}/{f.inspected_through} rejected through it
                </p>
              </div>
              <div className="grid gap-1.5">
                <RateBar label="Through" pct={f.rate_through_pct} max={maxRate} fill={barFill[verdictTone[f.verdict]]} />
                <RateBar label="Elsewhere" pct={f.rate_outside_pct} max={maxRate} fill="bg-idle" />
              </div>
              <p className="num text-sm text-ink lg:text-right">
                <span className="text-muted lg:hidden">Lift </span>
                <span className="font-semibold">{formatLift(f.lift)}</span>
              </p>
              <div>
                <Badge tone={verdictTone[f.verdict]}>{verdictLabel[f.verdict]}</Badge>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function RateBar({ label, pct, max, fill }: { label: string; pct: number | null; max: number; fill: string }) {
  const width = pct == null ? 0 : Math.max(1, (pct / max) * 100);
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_3.5rem] items-center gap-2 text-xs">
      <span className="text-muted">{label}</span>
      <div className="h-2 overflow-hidden rounded-full bg-idle-soft" role="presentation">
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
      </div>
      <span className="num text-right text-ink">{formatPct(pct)}</span>
    </div>
  );
}

function Coincidental({ factors }: { factors: CauseFactor[] }) {
  if (factors.length === 0) return null;
  return (
    <Card title="Why these are not the cause" subtitle="The rejected rolls passed through them, but so did plenty of good ones">
      <ul className="grid gap-3">
        {factors.map((f) => (
          <li key={`${f.factor_kind}-${f.factor_label}`} className="flex items-start gap-3 text-sm text-ink">
            <Badge tone={verdictTone[f.verdict]} className="mt-0.5 shrink-0">
              {verdictLabel[f.verdict]}
            </Badge>
            <span>{whyCoincidental(f)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
