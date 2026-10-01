/**
 * Lineage from data to decision as a vertical flow of small cards joined by arrows (pure HTML and CSS).
 * Nodes are placed in layers by their dependencies, so the two inputs of the labels (the data and the definition of
 * default) sit side by side. The flow ends at "decision": either the promotion, or a note that nothing decides with
 * this model yet.
 */
import { Link } from "react-router-dom";
import type { LineageGraph, ModelRef } from "../../api/types";
import { EmptyState } from "../ui";
import "./modeldetail.css";

type Node = LineageGraph["nodes"][number];

const TYPE_LABEL: Record<Node["type"], string> = {
  data: "Data",
  definition: "Definition of default",
  labels: "Labels",
  features: "Features",
  run: "Training run",
  model: "Model",
  evaluation: "Validation",
  gate: "Holdout gate",
  approval: "Approval",
  promotion: "Promotion",
};

function layers(nodes: Node[], edges: LineageGraph["edges"]): Node[][] {
  const ids = new Set(nodes.map((n) => n.id));
  const preds = new Map<string, string[]>();
  for (const e of edges) if (ids.has(e.from) && ids.has(e.to)) preds.set(e.to, [...(preds.get(e.to) ?? []), e.from]);
  const depth = new Map<string, number>();
  const visit = (id: string, path: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (path.has(id)) return 0; // a cycle cannot be layered; treat the back edge as a source
    path.add(id);
    const ps = preds.get(id) ?? [];
    const d = ps.length ? 1 + Math.max(...ps.map((p) => visit(p, path))) : 0;
    path.delete(id);
    depth.set(id, d);
    return d;
  };
  nodes.forEach((n) => visit(n.id, new Set()));
  const max = Math.max(0, ...depth.values());
  return Array.from({ length: max + 1 }, (_, i) => nodes.filter((n) => depth.get(n.id) === i)).filter((l) => l.length > 0);
}

function Arrow() {
  return (
    <span className="modeldetail-arrow" aria-hidden>
      <svg width="16" height="26" viewBox="0 0 16 26">
        <path d="M8 1 V21 M3 16 L8 22 L13 16" fill="none" style={{ stroke: "var(--faint)" }} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function LineageFlow({ graph, current, nothingServing }: { graph: LineageGraph; current: ModelRef; nothingServing?: boolean }) {
  if (graph.nodes.length === 0) return <EmptyState title="No lineage recorded">Lineage appears once the version has a training run and an evaluation.</EmptyState>;
  const rows = layers(graph.nodes, graph.edges);
  const promoted = graph.nodes.some((n) => n.type === "promotion");
  return (
    <ol className="modeldetail-flow" aria-label={`Lineage of ${current.label}, from data to decision`}>
      {rows.map((layer, i) => (
        <li key={i} className="modeldetail-layer">
          <ul>
            {layer.map((raw) => {
              const n = /^0 features/.test(raw.label) && raw.type === "features" ? { ...raw, label: "No features recorded", detail: "The harness has not evaluated this version." } : raw;
              const here = n.type === "model";
              return (
                <li key={n.id} className={`modeldetail-node ${here ? "here" : ""}`}>
                  <span className="type">{TYPE_LABEL[n.type] ?? n.type}</span>
                  {/* the model node is this page; the API's link for it may use a short model name, so it is not followed */}
                  <span className="label">{n.href && !here ? <Link to={n.href}>{n.label}</Link> : n.label}</span>
                  {n.detail && <span className={`detail ${n.type === "run" ? "mono" : ""}`}>{n.detail}</span>}
                  {here && <span className="xs muted">This page</span>}
                </li>
              );
            })}
          </ul>
          {(i < rows.length - 1 || !promoted) && <Arrow />}
        </li>
      ))}
      {!promoted && (
        <li className="modeldetail-layer">
          <ul>
            <li className="modeldetail-node pending">
              <span className="type">Decision</span>
              <span className="label">Not used for decisions</span>
              <span className="detail">
                {current.label} has not been promoted, so no decision uses it.
                {nothingServing ? " The legacy policy score still decides until a person approves a promotion." : ""}
              </span>
            </li>
          </ul>
        </li>
      )}
    </ol>
  );
}
