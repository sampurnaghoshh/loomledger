// Genealogy graph: yarn → greige → finished, laid out by hand in columns (no layout library).
import { memo, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Background, Controls, Handle, Position, ReactFlow, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Custody, GraphNode, LotGraph as LotGraphData, LotKind } from "@/api/types";
import { Badge } from "@/components/ui";
import { formatQty, humanize } from "@/lib/format";
import { custodyLabel, custodyTone, lotStatusTone, type Tone } from "@/lib/tones";

const KIND_ORDER: LotKind[] = ["yarn", "greige", "finished"];
const NODE_W = 210;
const COL_GAP = 90;
const DENSE_COLUMN = 6; // a column with more lots than this switches to compact nodes
const FANOUT_LABEL = 3; // a parent with more children than this gets one quantity label instead of one per edge
const FULL = { h: 96, gap: 16 };
const COMPACT = { h: 48, gap: 12 };
const FIT = { padding: 0.1, minZoom: 0.2 };

// Literal class strings so Tailwind generates them.
const toneBox: Record<Tone, string> = {
  ok: "bg-ok-soft border-ok/50",
  warn: "bg-warn-soft border-warn/50",
  bad: "bg-bad-soft border-bad/50",
  hold: "bg-hold-soft border-hold/50",
  brand: "bg-brand-soft border-brand/40",
  accent: "bg-accent-soft border-accent/50",
  idle: "bg-surface border-line",
};
const kindTone: Record<LotKind, Tone> = { yarn: "accent", greige: "idle", finished: "brand" };

type ColorBy = "kind" | "custody";
type LotNodeData = {
  lot: GraphNode;
  colorBy: ColorBy;
  compact: boolean;
  highlighted: boolean;
  root: boolean;
  rootLabel: string;
  outLabel: string | null; // shared quantity label for a big fan-out
  dimmed: boolean;
};
type LotFlowNode = Node<LotNodeData, "lot">;

/** Custody for produced lots; yarn has none, so fall back to its stored status. */
function nodeTone(lot: GraphNode, colorBy: ColorBy): Tone {
  if (colorBy === "kind") return kindTone[lot.kind];
  return lot.custody ? custodyTone[lot.custody] : lotStatusTone[lot.status];
}
function statusText(lot: GraphNode): string {
  return lot.custody ? custodyLabel[lot.custody] : humanize(lot.status);
}

const LotNode = memo(function LotNode({ data }: NodeProps<LotFlowNode>) {
  const { lot, colorBy, compact, highlighted, root, rootLabel, outLabel, dimmed } = data;
  const tone = nodeTone(lot, colorBy);
  const atCustomer = colorBy === "custody" && lot.custody === "at_customer";
  const held = lot.status === "quarantined" || lot.status === "recalled";
  const size = compact ? COMPACT : FULL;

  const box = root
    ? "border-2 border-bad bg-bad-soft ring-4 ring-bad/25"
    : atCustomer
      ? "border-2 border-accent bg-accent-soft ring-4 ring-accent/30 shadow-lg"
      : `border ${toneBox[tone]}`;
  const ring = highlighted && !root ? "ring-2 ring-brand ring-offset-2" : "";

  const badge = root ? (
    <Badge tone="bad">{rootLabel}</Badge>
  ) : colorBy === "custody" ? (
    <Badge tone={tone}>{statusText(lot)}</Badge>
  ) : (
    <span className="text-[10px] font-medium uppercase tracking-wide text-muted">{lot.kind}</span>
  );
  const where = lot.kind === "yarn" ? lot.supplier : [lot.machine, lot.shift].filter(Boolean).join(" · ");

  return (
    <div
      style={{ width: NODE_W, height: size.h }}
      className={`relative flex flex-col justify-center overflow-visible rounded-lg text-xs text-ink shadow-sm transition-opacity ${compact ? "px-2.5 py-1" : "px-3 py-2"} ${box} ${ring} ${dimmed ? "opacity-25" : ""}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <div className="flex items-center justify-between gap-2">
        <span className="whitespace-nowrap font-mono text-sm font-semibold">{lot.code}</span>
        {badge}
      </div>
      {compact ? (
        <p className="truncate text-muted">{(lot.kind === "greige" ? lot.machine : where) || "—"}</p>
      ) : (
        <>
          <p className="truncate text-muted">{lot.product}</p>
          <p className="num">
            <span className="font-medium">{formatQty(lot.qty, lot.uom)}</span>
            {root && <span className="text-muted"> · {statusText(lot)}</span>}
          </p>
          <p className="truncate text-muted">{where || "—"}</p>
        </>
      )}
      {held && (
        <Badge tone="hold" className="absolute -top-2.5 right-2">
          {humanize(lot.status)}
        </Badge>
      )}
      {outLabel && (
        <span className="num absolute top-1/2 left-full ml-2 -translate-y-1/2 whitespace-nowrap rounded bg-surface px-1.5 py-0.5 text-[11px] text-muted">
          {outLabel}
        </span>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  );
});

const nodeTypes = { lot: LotNode };

/**
 * Columns by kind. Each column is ordered by parent row, children are placed level with their parents,
 * then parents are re-centred on their children, so 1:1 chains are straight lines and fan-outs are balanced.
 */
function layout(graph: LotGraphData, colorBy: ColorBy, highlight: Set<string>, root: string | undefined, rootLabel: string) {
  const byCode = new Map(graph.nodes.map((n) => [n.code, n]));
  const parents = new Map<string, string[]>();
  const children = new Map<string, string[]>();
  for (const e of graph.edges) {
    parents.set(e.to, [...(parents.get(e.to) ?? []), e.from]);
    children.set(e.from, [...(children.get(e.from) ?? []), e.to]);
  }

  const columns = KIND_ORDER.map((k) => graph.nodes.filter((n) => n.kind === k)).filter((c) => c.length > 0);
  const dense = columns.some((c) => c.length > DENSE_COLUMN);
  const sizeOf = (col: GraphNode[]) => (col.length > DENSE_COLUMN ? COMPACT : FULL);
  const centre = new Map<string, number>(); // vertical centre of each lot
  const mean = (codes: string[]) => {
    const ys = codes.map((c) => centre.get(c)).filter((y): y is number => y != null);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
  };
  const spread = (col: GraphNode[]) => {
    const { h, gap } = sizeOf(col);
    for (let i = 1; i < col.length; i++) {
      const prev = centre.get(col[i - 1].code)!;
      centre.set(col[i].code, Math.max(centre.get(col[i].code)!, prev + h + gap));
    }
  };

  // Pass 1 (left → right): order by parent, sit level with the parent, keep a minimum gap.
  for (const col of columns) {
    const parentY = (n: GraphNode) => mean(parents.get(n.code) ?? []) ?? Infinity;
    col.sort((a, b) => parentY(a) - parentY(b) || a.code.localeCompare(b.code));
    col.forEach((n) => centre.set(n.code, parentY(n) === Infinity ? -Infinity : parentY(n)));
    centre.set(col[0].code, Math.max(0, centre.get(col[0].code)!));
    spread(col);
  }
  // Pass 2 (right → left): centre each parent on its children.
  for (const col of [...columns].reverse()) {
    col.forEach((n) => {
      const y = mean(children.get(n.code) ?? []);
      if (y != null) centre.set(n.code, y);
    });
    spread(col);
  }

  // Fan-outs: one label beside the parent ("15.6 kg each" or the total) instead of one per edge.
  const outLabel = new Map<string, string>();
  const quiet = new Set<string>();
  for (const [from, kids] of children) {
    const parent = byCode.get(from);
    if (!parent || kids.length <= FANOUT_LABEL) continue;
    const qtys = graph.edges.filter((e) => e.from === from).map((e) => e.qty_consumed);
    const same = qtys.every((q) => q === qtys[0]);
    outLabel.set(from, same ? `${formatQty(qtys[0], parent.uom)} each` : `${formatQty(qtys.reduce((a, b) => a + b, 0), parent.uom)} total`);
    quiet.add(from);
  }

  const nodes: LotFlowNode[] = columns.flatMap((col, ci) => {
    const { h } = sizeOf(col);
    return col.map((lot) => ({
      id: lot.code,
      type: "lot" as const,
      position: { x: ci * (NODE_W + COL_GAP), y: centre.get(lot.code)! - h / 2 },
      data: {
        lot,
        colorBy,
        compact: col.length > DENSE_COLUMN,
        highlighted: highlight.has(lot.code),
        root: lot.code === root,
        rootLabel,
        outLabel: outLabel.get(lot.code) ?? null,
        dimmed: false,
      },
      draggable: false,
      connectable: false,
      selectable: false,
    }));
  });

  const edges: Edge[] = graph.edges.map((e) => {
    const from = byCode.get(e.from);
    const fromRoot = e.from === root;
    return {
      id: `${e.from}->${e.to}`,
      source: e.from,
      target: e.to,
      label: quiet.has(e.from) ? undefined : from ? formatQty(e.qty_consumed, from.uom) : String(e.qty_consumed),
      style: { stroke: fromRoot ? "var(--color-bad)" : "var(--color-muted)", strokeWidth: fromRoot ? 2 : 1.25 },
      labelStyle: { fill: "var(--color-muted)", fontSize: 11 },
      labelBgStyle: { fill: "var(--color-surface)" },
      labelBgPadding: [4, 2] as [number, number],
    };
  });
  return { nodes, edges, dense };
}

/** Re-fit whenever the canvas changes size (rotation, sidebar, window resize). */
function FitOnResize({ target }: { target: RefObject<HTMLDivElement | null> }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const el = target.current;
    if (!el) return;
    const ro = new ResizeObserver(() => void fitView(FIT));
    ro.observe(el);
    return () => ro.disconnect();
  }, [fitView, target]);
  return null;
}

export function LotGraph({
  graph,
  highlight = [],
  rootCause,
  rootLabel = "Root cause",
  colorBy,
}: {
  graph: LotGraphData;
  highlight?: string[];
  rootCause?: string;
  rootLabel?: string;
  colorBy: ColorBy;
}) {
  const highlightKey = highlight.join(",");
  const base = useMemo(
    () => layout(graph, colorBy, new Set(highlight), rootCause, rootLabel),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, colorBy, highlightKey, rootCause, rootLabel],
  );
  const [focusCustody, setFocusCustody] = useState<Custody | null>(null);
  const nodes = useMemo(
    () =>
      focusCustody
        ? base.nodes.map((n) => ({ ...n, data: { ...n.data, dimmed: n.data.lot.custody !== focusCustody } }))
        : base.nodes,
    [base, focusCustody],
  );
  const canvas = useRef<HTMLDivElement>(null);
  // Re-mount when the data changes so fitView runs on the new graph.
  const flowKey = `${base.nodes.map((n) => n.id).join(",")}|${rootCause ?? ""}`;

  return (
    <div className="grid gap-3">
      <div
        ref={canvas}
        className={`w-full min-w-0 overflow-hidden rounded-lg border border-line bg-canvas ${base.dense ? "h-105 md:h-180" : "h-90 md:h-105"}`}
      >
        <ReactFlow
          key={flowKey}
          nodes={nodes}
          edges={base.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={FIT}
          minZoom={0.1}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          zoomOnPinch
          zoomOnDoubleClick
          panOnDrag
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--color-line)" gap={20} />
          <Controls showInteractive={false} fitViewOptions={FIT} />
          <FitOnResize target={canvas} />
        </ReactFlow>
      </div>
      <Legend
        graph={graph}
        colorBy={colorBy}
        hasHighlight={highlight.length > 0}
        rootLabel={rootCause ? rootLabel : null}
        focus={focusCustody}
        onFocus={(c) => setFocusCustody((cur) => (cur === c ? null : c))}
      />
    </div>
  );
}

function Legend({
  graph,
  colorBy,
  hasHighlight,
  rootLabel,
  focus,
  onFocus,
}: {
  graph: LotGraphData;
  colorBy: ColorBy;
  hasHighlight: boolean;
  rootLabel: string | null;
  focus: Custody | null;
  onFocus: (c: Custody) => void;
}) {
  const extras = (
    <>
      {rootLabel && <Badge tone="bad">{rootLabel}</Badge>}
      {hasHighlight && <span className="rounded-full px-2 py-0.5 text-muted ring-2 ring-brand">Selected roll</span>}
    </>
  );
  if (colorBy === "kind") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {KIND_ORDER.filter((k) => graph.nodes.some((n) => n.kind === k)).map((k) => (
          <Badge key={k} tone={kindTone[k]}>
            {humanize(k)}
          </Badge>
        ))}
        {extras}
      </div>
    );
  }
  const counts = new Map<Custody, number>();
  for (const n of graph.nodes) if (n.custody) counts.set(n.custody, (counts.get(n.custody) ?? 0) + 1);
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {[...counts].map(([c, n]) => (
        <button
          key={c}
          type="button"
          aria-pressed={focus === c}
          title={focus === c ? "Show all lots" : `Highlight: ${custodyLabel[c]}`}
          onClick={() => onFocus(c)}
          className={`rounded-full ${focus && focus !== c ? "opacity-40" : ""}`}
        >
          <Badge tone={custodyTone[c]} className={c === "at_customer" || focus === c ? "ring-2 ring-accent" : undefined}>
            {custodyLabel[c]} · {n}
          </Badge>
        </button>
      ))}
      {extras}
      {focus && <span className="text-muted">Tap again to show all</span>}
    </div>
  );
}
