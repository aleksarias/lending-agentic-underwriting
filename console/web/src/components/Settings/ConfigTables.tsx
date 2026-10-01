/**
 * Renders nested configuration readably: flat groups as setting / value / meaning tables, groups of groups (agent
 * caps, protected classes) as matrices, lists as chips. Raw JSON is available behind a toggle only.
 */
import { useState, type ReactNode } from "react";
import { fmtNum, fmtPct, fmtUsd } from "../../lib/format";
import { Card, EmptyState, Json, Section } from "../ui";
import { GROUP_TITLES, groupNote, humanize, metaFor, type Fmt } from "./meta";

type Dict = Record<string, unknown>;
const isObj = (v: unknown): v is Dict => !!v && typeof v === "object" && !Array.isArray(v);
const isScalar = (v: unknown) => v == null || typeof v !== "object";
const isFlat = (o: Dict) => Object.values(o).every((v) => isScalar(v) || (Array.isArray(v) && v.every(isScalar)));

/** 0.002 -> "0.002", 5 -> "5", 0.30000000000000004 -> "0.3" */
const trimmed = (v: number) => (Number.isInteger(v) ? fmtNum(v) : String(Number(v.toPrecision(6))));

function format(v: number, fmt: Fmt | undefined): ReactNode {
  switch (fmt) {
    case "pct":
      return fmtPct(v, Number.isInteger(Math.round(v * 1000) / 10) ? 0 : 1);
    case "usd":
      return fmtUsd(v);
    case "min":
      return `${trimmed(v)} min`;
    case "dbu":
      return `${trimmed(v)} DBU`;
    case "count":
      return fmtNum(v);
    default:
      return trimmed(v);
  }
}

export function Value({ path, value }: { path: string[]; value: unknown }) {
  const fmt = metaFor(path)?.fmt;
  if (value == null) return <span className="muted">—</span>;
  if (Array.isArray(value)) {
    return value.length ? (
      <span className="row" style={{ gap: 4 }}>
        {value.map((x, i) => (
          <span key={i} className="badge mono">
            {String(x)}
          </span>
        ))}
      </span>
    ) : (
      <span className="muted">none</span>
    );
  }
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "number") return <span className="num">{format(value, fmt)}</span>;
  return fmt === "mono" ? <span className="mono">{String(value)}</span> : <>{String(value)}</>;
}

function LeafTable({ path, data }: { path: string[]; data: Dict }) {
  const rows = Object.entries(data).map(([k, v]) => {
    const m = metaFor([...path, k]);
    return { key: k, label: m?.label ?? m?.keyLabel?.(k) ?? humanize(k), hint: m?.hint, value: v };
  });
  const anyHint = rows.some((r) => r.hint);
  return (
    <div className="table-wrap" style={{ border: 0 }}>
      <table className="data" style={{ tableLayout: "fixed", minWidth: 560 }}>
        <colgroup>
          <col style={{ width: anyHint ? "34%" : "50%" }} />
          <col style={{ width: anyHint ? "22%" : "50%" }} />
          {anyHint && <col />}
        </colgroup>
        <thead>
          <tr>
            <th>Setting</th>
            <th>Value</th>
            {anyHint && <th>What it does</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>
                {r.label}
                <div className="xs faint mono">{r.key}</div>
              </td>
              <td>
                <Value path={[...path, r.key]} value={r.value} />
              </td>
              {anyHint && <td className="small muted">{r.hint ?? ""}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MatrixTable({ path, data }: { path: string[]; data: Record<string, Dict> }) {
  const cols: string[] = [];
  for (const row of Object.values(data)) for (const k of Object.keys(row)) if (!cols.includes(k)) cols.push(k);
  const rowLabel = (k: string) => metaFor([...path, k])?.keyLabel?.(k) ?? humanize(k);
  return (
    <div className="table-wrap" style={{ border: 0 }}>
      <table className="data">
        <thead>
          <tr>
            <th>{isRole(path) ? "Agent" : "Name"}</th>
            {cols.map((c) => (
              <th key={c}>{metaFor([...path, "*", c])?.label ?? humanize(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([rk, row]) => (
            <tr key={rk}>
              <td>{rowLabel(rk)}</td>
              {cols.map((c) => (
                <td key={c}>
                  <Value path={[...path, rk, c]} value={row[c]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const isRole = (path: string[]) => path.join(".") === "budgets.agents";

/** One configuration object (for example all thresholds) as a stack of titled cards. */
export function ConfigSection({ root, data }: { root: string; data: Dict }) {
  const flatTop: Dict = {};
  const blocks: ReactNode[] = [];
  for (const [k, v] of Object.entries(data)) {
    const path = [root, k];
    const title = GROUP_TITLES[path.join(".")] ?? humanize(k);
    if (isObj(v) && isFlat(v)) {
      blocks.push(
        <Card key={k} title={title}>
          <LeafTable path={path} data={v} />
          {groupNote(path.join(".")) && <div className="xs muted" style={{ marginTop: 6 }}>{groupNote(path.join("."))}</div>}
        </Card>,
      );
    } else if (isObj(v) && Object.values(v).every((x) => isObj(x) && isFlat(x))) {
      blocks.push(
        <Card key={k} title={title}>
          <MatrixTable path={path} data={v as Record<string, Dict>} />
        </Card>,
      );
    } else if (isObj(v)) {
      blocks.push(
        <Card key={k} title={title}>
          <ConfigSection root={path.join(".")} data={v} />
        </Card>,
      );
    } else {
      flatTop[k] = v;
    }
  }
  if (Object.keys(flatTop).length) {
    blocks.push(
      <Card key="__flat" title={GROUP_TITLES[`${root}.__flat`] ?? (blocks.length ? "Other settings" : "Settings")}>
        <LeafTable path={[root]} data={flatTop} />
      </Card>,
    );
  }
  return <div className="stack" style={{ gap: "var(--gap)" }}>{blocks}</div>;
}

/** A titled configuration block with a "Show raw JSON" toggle; the JSON never shows by default. */
export function ConfigBlock({ id, title, note, root, data }: { id: string; title: string; note?: ReactNode; root: string; data: Dict }) {
  const [raw, setRaw] = useState(false);
  return (
    <Section
      id={id}
      title={title}
      note={note}
      right={
        <button type="button" className="btn small" aria-expanded={raw} onClick={() => setRaw((o) => !o)}>
          {raw ? "Hide raw JSON" : "Show raw JSON"}
        </button>
      }
    >
      {Object.keys(data).length === 0 ? (
        <EmptyState title="No settings to show">The console could not read this configuration. It comes from the YAML files in the repository's config folder.</EmptyState>
      ) : (
        <ConfigSection root={root} data={data} />
      )}
      {raw && <Json value={data} />}
    </Section>
  );
}
