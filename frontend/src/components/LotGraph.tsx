// Genealogy graph: yarn → greige → finished, laid out by hand in columns (no layout library).
import { memo, useMemo } from "react";
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Custody, GraphNode, LotGraph as LotGraphData, LotKind } from "@/api/types";
import { Badge } from "@/components/ui";
import { formatQty, humanize } from "@/lib/format";
import { custodyLabel, custodyTone, lotStatusTone, type Tone } from "@/lib/tones";

const KIND_ORDER: LotKind[] = ["yarn", "greige", "finished"];
const NODE_W = 210;
const COL_GAP = 90;
const ROW_H = 112;

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
type LotNodeData = { lot: GraphNode; colorBy: ColorBy; highlighted: boolean; rootCause: boolean };
type LotFlowNode = Node<LotNodeData, "lot">;

/** Custody for produced lots; yarn has none, so fall back to its stored status. */
function nodeTone(lot: GraphNode, colorBy: ColorBy): Tone {
  if (colorBy === "kind") return kindTone[lot.kind];
  return lot.custody ? custodyTone[lot.custody] : lotStatusTone[lot.status];
}
function nodeLabel(lot: GraphNode): string {
  return lot.custody ? custodyLabel[lot.custody] : humanize(lot.status);
}

const LotNode = memo(function LotNode({ data }: NodeProps<LotFlowNode>) {
  const { lot, colorBy, highlighted, rootCause } = data;
  const tone = nodeTone(lot, colorBy);
  const atCustomer = colorBy === "custody" && lot.custody === "at_customer";
  const held = lot.status === "quarantined" || lot.status === "recalled";

  const box = rootCause
    ? "border-2 border-bad bg-bad-soft ring-4 ring-bad/25"
    : atCustomer
      ? "border-2 border-accent bg-accent-soft ring-4 ring-accent/30 shadow-lg"
      : `border ${toneBox[tone]}`;

  return (
    <div
      style={{ width: NODE_W }}
      className={`rounded-lg px-3 py-2 text-xs text-ink shadow-sm ${box} ${highlighted && !rootCause ? "ring-2 ring-brand ring-offset-2" : ""}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} style={{ opacity: 0 }} />
      <div className="flex items-center justify-between gap-2">
        <span className="whitespace-nowrap font-mono text-sm font-semibold">{lot.code}</span>
        {rootCause ? (
          <Badge tone="bad">Root cause</Badge>
        ) : colorBy === "custody" ? (
          <Badge tone={tone}>{nodeLabel(lot)}</Badge>
        ) : (
          <span className="text-[10px] font-medium uppercase tracking-wide text-muted">{lot.kind}</span>
        )}
      </div>
      <p className="mt-0.5 truncate text-muted">{lot.product}</p>
      <p className="num font-medium">{formatQty(lot.qty, lot.uom)}</p>
      <p className="truncate text-muted">
        {lot.kind === "yarn" ? (lot.supplier ?? "—") : [lot.machine, lot.shift].filter(Boolean).join(" · ") || "—"}
      </p>
      {held && (
        <Badge tone="hold" className="mt-1">
          {humanize(lot.status)}
        </Badge>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} style={{ opacity: 0 }} />
    </div>
  );
});

const nodeTypes = { lot: LotNode };

/** Columns by kind; within a column each lot sits next to its parent (parent row, then code). */
function layout(graph: LotGraphData, colorBy: ColorBy, highlight: Set<string>, rootCause?: string) {
  const byCode = new Map(graph.nodes.map((n) => [n.code, n]));
  const parents = new Map<string, string[]>();
  for (const e of graph.edges) parents.set(e.to, [...(parents.get(e.to) ?? []), e.from]);

  const columns = KIND_ORDER.map((k) => graph.nodes.filter((n) => n.kind === k)).filter((c) => c.length > 0);
  const row = new Map<string, number>();
  for (const col of columns) {
    const parentRow = (n: GraphNode) => Math.min(Infinity, ...(parents.get(n.code) ?? []).map((p) => row.get(p) ?? Infinity));
    col.sort((a, b) => parentRow(a) - parentRow(b) || a.code.localeCompare(b.code));
    col.forEach((n, i) => row.set(n.code, i));
  }

  const tallest = Math.max(...columns.map((c) => c.length));
  const nodes: LotFlowNode[] = columns.flatMap((col, ci) => {
    const offset = ((tallest - col.length) * ROW_H) / 2;
    return col.map((lot, ri) => ({
      id: lot.code,
      type: "lot" as const,
      position: { x: ci * (NODE_W + COL_GAP), y: offset + ri * ROW_H },
      data: { lot, colorBy, highlighted: highlight.has(lot.code), rootCause: lot.code === rootCause },
      draggable: false,
      connectable: false,
      selectable: false,
    }));
  });

  const edges: Edge[] = graph.edges.map((e) => {
    const from = byCode.get(e.from);
    const fromRoot = e.from === rootCause;
    return {
      id: `${e.from}->${e.to}`,
      source: e.from,
      target: e.to,
      label: from ? formatQty(e.qty_consumed, from.uom) : String(e.qty_consumed),
      style: { stroke: fromRoot ? "var(--color-bad)" : "var(--color-muted)", strokeWidth: fromRoot ? 2 : 1.25 },
      labelStyle: { fill: "var(--color-muted)", fontSize: 11 },
      labelBgStyle: { fill: "var(--color-surface)" },
      labelBgPadding: [4, 2] as [number, number],
    };
  });
  // Initial framing: the lots the viewer must see first (at-customer rolls / root cause) and the path back to the source.
  const focus = new Set<string>();
  const visit = (code: string) => {
    if (focus.has(code)) return;
    focus.add(code);
    (parents.get(code) ?? []).forEach(visit);
  };
  graph.nodes
    .filter((n) => n.code === rootCause || (colorBy === "custody" && n.custody === "at_customer"))
    .forEach((n) => visit(n.code));
  return { nodes, edges, focus: focus.size > 1 ? [...focus] : nodes.map((n) => n.id) };
}

export function LotGraph({
  graph,
  highlight = [],
  rootCause,
  colorBy,
}: {
  graph: LotGraphData;
  highlight?: string[];
  rootCause?: string;
  colorBy: ColorBy;
}) {
  const highlightKey = highlight.join(",");
  const { nodes, edges, focus } = useMemo(
    () => layout(graph, colorBy, new Set(highlight), rootCause),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, colorBy, highlightKey, rootCause],
  );
  // Desktop: keep text readable and let people pan. Phone: show the whole framed path, pinch to read.
  const wide = typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches;
  // Re-mount when the data changes so fitView runs again.
  const flowKey = `${nodes.map((n) => n.id).join(",")}|${rootCause ?? ""}`;

  return (
    <div className="grid gap-3">
      <div className="h-[360px] w-full min-w-0 overflow-hidden rounded-lg border border-line bg-canvas md:h-[420px]">
        <ReactFlow
          key={flowKey}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.12, nodes: focus.map((id) => ({ id })), minZoom: wide ? 0.45 : 0.1 }}
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
          <Controls showInteractive={false} fitViewOptions={{ padding: 0.08 }} />
        </ReactFlow>
      </div>
      <Legend graph={graph} colorBy={colorBy} hasHighlight={highlight.length > 0} hasRoot={!!rootCause} />
    </div>
  );
}

function Legend({ graph, colorBy, hasHighlight, hasRoot }: { graph: LotGraphData; colorBy: ColorBy; hasHighlight: boolean; hasRoot: boolean }) {
  if (colorBy === "kind") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {KIND_ORDER.filter((k) => graph.nodes.some((n) => n.kind === k)).map((k) => (
          <Badge key={k} tone={kindTone[k]}>
            {humanize(k)}
          </Badge>
        ))}
        {hasRoot && <Badge tone="bad">Root cause</Badge>}
        {hasHighlight && <span className="rounded-full px-2 py-0.5 ring-2 ring-brand">Selected roll</span>}
      </div>
    );
  }
  const counts = new Map<Custody, number>();
  for (const n of graph.nodes) if (n.custody) counts.set(n.custody, (counts.get(n.custody) ?? 0) + 1);
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {[...counts].map(([c, n]) => (
        <Badge key={c} tone={custodyTone[c]} className={c === "at_customer" ? "ring-2 ring-accent" : undefined}>
          {custodyLabel[c]} · {n}
        </Badge>
      ))}
    </div>
  );
}
