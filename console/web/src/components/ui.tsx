/**
 * Shared UI building blocks. Pages compose these; do not re-implement them per page.
 * Styling lives in styles/app.css (class names below).
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApiError } from "../api/client";
import type { BadgeSpec, DefinitionRef, ModelRef, Tile as TileT, Tone, Unavailable } from "../api/types";
import { fmtAgo, fmtDateTime, shortVersion } from "../lib/format";

export function Page({ children }: { children: ReactNode }) {
  return <div className="page">{children}</div>;
}

/** Every page opens with: eyebrow (screen group), title, one plain-language summary sentence, optional actions. */
export function PageHeader(props: { eyebrow?: string; title: string; summary?: ReactNode; actions?: ReactNode; meta?: ReactNode }) {
  return (
    <header className="page-header">
      {props.eyebrow && <div className="eyebrow">{props.eyebrow}</div>}
      <h1>{props.title}</h1>
      {props.summary && <div className="summary">{props.summary}</div>}
      {props.meta && <div className="row small muted">{props.meta}</div>}
      {props.actions && <div className="actions">{props.actions}</div>}
    </header>
  );
}

export function Section(props: { title: string; right?: ReactNode; children: ReactNode; id?: string; note?: ReactNode }) {
  return (
    <section className="section" id={props.id}>
      <div className="section-head">
        <h2>{props.title}</h2>
        {props.right}
      </div>
      {props.note && <div className="small muted">{props.note}</div>}
      {props.children}
    </section>
  );
}

/** kind="proposed" marks agent output; kind="measured" marks harness/production measurements. */
export function Card(props: { title?: string; children: ReactNode; kind?: "proposed" | "measured"; flush?: boolean; className?: string }) {
  const cls = ["card", props.kind ?? "", props.flush ? "flush" : "", props.className ?? ""].join(" ").trim();
  return (
    <div className={cls}>
      {props.title && <div className="card-title">{props.title}</div>}
      {props.children}
    </div>
  );
}

export function Pill({ tone = "neutral", children, dot }: { tone?: Tone | "info"; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`pill ${tone}`}>
      {dot && <span className="dot" aria-hidden />}
      {children}
    </span>
  );
}

export function Badges({ items }: { items: BadgeSpec[] }) {
  return (
    <span className="row">
      {items.map((b, i) => (
        <Pill key={i} tone={b.tone}>
          {b.label}
        </Pill>
      ))}
    </span>
  );
}

/** Marks a piece of content as an agent claim or a measurement. */
export function KindTag({ kind }: { kind: "proposed" | "measured" | "system" }) {
  if (kind === "system") return <span className="xs faint">system</span>;
  return <span className={`xs kind-${kind}`}>{kind === "proposed" ? "proposed" : "measured"}</span>;
}

export function Tile({ tile }: { tile: TileT }) {
  const body = (
    <>
      <span className="k">{tile.label}</span>
      <span className="v">{tile.value}</span>
      {tile.sub && <span className="s">{tile.sub}</span>}
    </>
  );
  const cls = `tile ${tile.tone ?? ""}`;
  return tile.href ? (
    <Link className={cls} to={tile.href}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export function Tiles({ tiles }: { tiles: TileT[] }) {
  return (
    <div className="tiles">
      {tiles.map((t) => (
        <Tile key={t.key} tile={t} />
      ))}
    </div>
  );
}

export function Banner({ tone = "neutral", title, children }: { tone?: Tone; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`banner ${tone}`} role={tone === "crit" ? "alert" : undefined}>
      {title && <div className="title">{title}</div>}
      {children && <div>{children}</div>}
    </div>
  );
}

export function DefinitionBadge({ def, version, to }: { def?: DefinitionRef | null; version?: string | null; to?: string }) {
  const v = def?.version ?? version ?? null;
  const label = def ? `${def.summary}` : null;
  const body = (
    <>
      <span className="mono">{shortVersion(v)}</span>
      {label && <span>{label}</span>}
    </>
  );
  const href = to ?? (v ? `/definitions/${v}` : undefined);
  return href ? (
    <Link className="badge" to={href} title="Definition of default">
      {body}
    </Link>
  ) : (
    <span className="badge">{body}</span>
  );
}

export function ModelBadge({ model }: { model: ModelRef | null | undefined }) {
  if (!model) return <span className="badge">none</span>;
  const href = model.key === "legacy_score" ? undefined : `/models/${encodeURIComponent(model.name)}/${encodeURIComponent(model.version)}`;
  const body = (
    <>
      <strong>{model.label}</strong>
      {model.definition_version && <span className="mono">{shortVersion(model.definition_version)}</span>}
    </>
  );
  return href ? (
    <Link className="badge" to={href}>
      {body}
    </Link>
  ) : (
    <span className="badge">{body}</span>
  );
}

export function TimeAgo({ iso }: { iso: string | null | undefined }) {
  return <span title={fmtDateTime(iso)}>{fmtAgo(iso)}</span>;
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Loading({ label = "Loading…", height = 120 }: { label?: string; height?: number }) {
  return (
    <div className="skeleton" style={{ minHeight: height }} aria-busy="true" aria-label={label}>
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const e = error as Partial<ApiError> & { message?: string };
  return (
    <div className="error">
      <strong>Couldn’t load this data.</strong> {e?.detail ?? e?.message ?? String(error)}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="title">{title}</div>
      {children && <div className="small">{children}</div>}
      {action}
    </div>
  );
}

/** Renders an Unavailable payload (feature not built / not connected yet) as a designed empty state. */
export function UnavailableState({ u, title }: { u: Unavailable; title?: string }) {
  return (
    <EmptyState title={title ?? "Not available yet"}>
      <p style={{ margin: "4px 0" }}>{u.reason}</p>
      {u.requires.length > 0 && (
        <div className="small">
          Needs: {u.requires.join(" · ")}
        </div>
      )}
    </EmptyState>
  );
}

/** Standard query wrapper: loading skeleton, error box, or children(data). */
export function QueryView<T>({ query, children, loadingHeight }: { query: { data?: T; isLoading: boolean; error: unknown }; children: (data: T) => ReactNode; loadingHeight?: number }) {
  if (query.isLoading) return <Loading height={loadingHeight} />;
  if (query.error) return <ErrorState error={query.error} />;
  if (query.data === undefined) return <Loading height={loadingHeight} />;
  return <>{children(query.data)}</>;
}

export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: { key: K; label: ReactNode }[]; value: K; onChange: (k: K) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key} className={value === t.key ? "active" : ""} onClick={() => onChange(t.key)} type="button">
          {t.label}
        </button>
      ))}
    </div>
  );
}

export interface Column<R> {
  key: string;
  header: ReactNode;
  render: (row: R) => ReactNode;
  /** value used for sorting; omit to make the column unsortable */
  sort?: (row: R) => number | string | null | undefined;
  align?: "left" | "right";
  className?: (row: R) => string | undefined;
}

/** Simple sortable table. For wide data it scrolls horizontally inside its own container. */
export function DataTable<R>(props: { rows: R[]; columns: Column<R>[]; rowKey: (r: R) => string; onRowClick?: (r: R) => void; empty?: ReactNode; initialSort?: { key: string; dir: "asc" | "desc" }; maxHeight?: number }) {
  const [sort, setSort] = useState(props.initialSort ?? null);
  const rows = useMemo(() => {
    if (!sort) return props.rows;
    const col = props.columns.find((c) => c.key === sort.key);
    if (!col?.sort) return props.rows;
    const get = col.sort;
    return [...props.rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const c = x < y ? -1 : 1;
      return sort.dir === "asc" ? c : -c;
    });
  }, [props.rows, props.columns, sort]);
  if (!props.rows.length) return <>{props.empty ?? <EmptyState title="Nothing to show" />}</>;
  return (
    <div className="table-wrap" style={props.maxHeight ? { maxHeight: props.maxHeight, overflowY: "auto" } : undefined}>
      <table className="data">
        <thead>
          <tr>
            {props.columns.map((c) => (
              <th
                key={c.key}
                className={[c.align === "right" ? "r" : "", c.sort ? "sortable" : ""].join(" ")}
                onClick={c.sort ? () => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "desc" })) : undefined}
                aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                {c.header}
                {sort?.key === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={props.rowKey(r)} className={props.onRowClick ? "clickable" : undefined} onClick={props.onRowClick ? () => props.onRowClick!(r) : undefined}>
              {props.columns.map((c) => (
                <td key={c.key} className={[c.align === "right" ? "r" : "", c.className?.(r) ?? ""].join(" ")}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Horizontal meter for "used vs cap" budgets. */
export function Meter({ used, cap, label, unit = "" }: { used: number; cap: number; label: string; unit?: string }) {
  const pct = cap > 0 ? Math.min(100, (used / cap) * 100) : 0;
  const tone = pct >= 90 ? "crit" : pct >= 75 ? "warn" : "";
  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row between small">
        <span>{label}</span>
        <span className="num muted">
          {used.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          {unit} of {cap.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          {unit}
        </span>
      </div>
      <div className="bar-track" role="meter" aria-valuenow={used} aria-valuemin={0} aria-valuemax={cap} aria-label={label}>
        <div className={`bar-fill ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** In-page confirmation dialog (browser confirm() is not used). */
export function ConfirmDialog(props: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireText?: { label: string; minLength: number };
  busy?: boolean;
  onConfirm: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  if (!props.open) return null;
  const ok = !props.requireText || text.trim().length >= props.requireText.minLength;
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={props.title}>
      <div className="dialog">
        <h3>{props.title}</h3>
        <div className="small">{props.children}</div>
        {props.requireText && (
          <label className="field">
            {props.requireText.label}
            <textarea value={text} onChange={(e) => setText(e.target.value)} />
          </label>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" type="button" onClick={props.onCancel} disabled={props.busy}>
            Cancel
          </button>
          <button className={`btn ${props.danger ? "danger" : "primary"}`} type="button" disabled={!ok || props.busy} onClick={() => props.onConfirm(text.trim())}>
            {props.busy ? "Working…" : props.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CodeBlock({ children }: { children: ReactNode }) {
  return <pre className="code">{children}</pre>;
}

export function Json({ value }: { value: unknown }) {
  return <CodeBlock>{JSON.stringify(value, null, 2)}</CodeBlock>;
}

/** Link helpers so every page links the same way. */
export const links = {
  model: (name: string, version: string) => `/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}`,
  evaluation: (evalId: string) => `/performance/evaluations/${encodeURIComponent(evalId)}`,
  cycle: (cycleId: string) => `/history/cycles/${encodeURIComponent(cycleId)}`,
  definition: (version: string) => `/definitions/${encodeURIComponent(version)}`,
  report: (reportId: string) => `/agents/reports/${encodeURIComponent(reportId)}`,
  approval: (candidateRef: string) => `/approvals/${encodeURIComponent(candidateRef)}`,
  variable: (name: string) => `/data/${encodeURIComponent(name)}`,
};
