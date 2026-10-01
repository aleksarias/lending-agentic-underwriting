/**
 * Small building blocks shared by the Models, Performance, Fairness and Data screens (and their detail screens):
 * model status pill, definition selector and URL state, horizontal bars with exact values, and 404 handling.
 * If any of these proves useful elsewhere it can move into components/ui.tsx.
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { DefinitionRef, DefinitionVersion, ModelRef, ModelStatus, ModelVersion, Tone } from "../../api/types";
import { checkLabel, fmtNum } from "../../lib/format";
import { DefinitionBadge, EmptyState, ErrorState, Loading, Pill } from "../ui";
import "./models.css";

// ------------------------------------------------------------------------------------------------ model status
const STATUS_TONE: Record<ModelStatus, Tone | "info"> = {
  serving: "good",
  champion: "accent",
  challenger: "info",
  candidate: "neutral",
  baseline: "neutral",
  retired: "neutral",
  superseded: "warn",
};

export const STATUS_ORDER: ModelStatus[] = ["serving", "champion", "challenger", "candidate", "baseline", "retired", "superseded"];

export const STATUS_HELP: Record<ModelStatus, string> = {
  serving: "Makes live decisions.",
  champion: "Promoted for its definition of default. It is serving only when its status says serving.",
  challenger: "The current challenger for its definition of default (it holds the challenger alias for that definition).",
  candidate: "Registered by an improvement cycle and not selected as challenger.",
  baseline: "Trained by the pipeline as the reference for its definition of default.",
  retired: "Withdrawn from use.",
  superseded: "Marked superseded because its definition of default was replaced.",
};

export function StatusPill({ status }: { status: ModelStatus }) {
  return (
    <span title={STATUS_HELP[status]}>
      <Pill tone={STATUS_TONE[status]}>{status}</Pill>
    </span>
  );
}

/** checkLabel with the acronyms in capitals: "no_proxy_features" -> "No proxy features", "holdout_auc" -> "Holdout AUC". */
export const checkName = (key: string) => checkLabel(key).replace(/\bauc\b/gi, "AUC").replace(/\bpsi\b/gi, "PSI");

const MODEL_TYPES: Record<string, string> = { logreg: "Logistic regression", lightgbm: "LightGBM", xgboost: "XGBoost" };
export const modelTypeLabel = (t: string | null | undefined) => (t ? (MODEL_TYPES[t] ?? t) : "—");

export const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

/** "candidate:11" -> "11"; "baseline:10" -> "10". */
export const versionOfRef = (ref: string | null | undefined) => {
  const i = ref ? ref.indexOf(":") : -1;
  return ref && i >= 0 ? ref.slice(i + 1) : null;
};
export const isBaselineRef = (ref: string | null | undefined) => !!ref && ref.startsWith("baseline:");

/** The registered model behind an evaluation ref such as "candidate:11" (needs the registry list for the name). */
export function modelOfRef(models: ModelVersion[] | undefined, ref: string | null | undefined): ModelRef | undefined {
  const v = versionOfRef(ref);
  if (!v || !models) return undefined;
  // candidate versions are labeled "v11"; production versions "prod v1", so the label separates the two registries
  return models.find((m) => m.model.label === `v${v}`)?.model;
}

// ------------------------------------------------------------------------------------------------ definitions
/** A DefinitionRef (what DefinitionBadge and the selectors use) built from a full DefinitionVersion. */
export function definitionRefOf(d: DefinitionVersion): DefinitionRef {
  const f = d.fields ?? {};
  const dpd = Number(f.delinquency_threshold_dpd ?? 0);
  const ever = (f.delinquency_timing ?? "ever") === "ever";
  const months = Number(f.observation_window_months ?? 0);
  return {
    version: d.version,
    short: d.short,
    name: d.name,
    summary: `${dpd} DPD ${ever ? "ever" : "at end of window"} / ${months} months`,
    dpd,
    timing: ever ? "ever" : "end_of_window",
    window_months: months,
  };
}

/** Resolve the ?def= value (full hash, 8-character short form or unique prefix) against the known definitions. */
export function pickDefinition(refs: DefinitionRef[], requested: string | undefined, fallback: string | null | undefined): DefinitionRef | undefined {
  if (requested) {
    const hit = refs.find((r) => r.version === requested || r.short === requested) ?? refs.find((r) => r.version.startsWith(requested));
    if (hit) return hit;
  }
  return refs.find((r) => r.version === fallback);
}

/** ?def= URL state. The parameter is dropped when the active definition is selected, so default links stay short. */
export function useDefinitionParam(activeVersion: string | null | undefined) {
  const [params, setParams] = useSearchParams();
  const requested = params.get("def") || undefined;
  const select = useCallback(
    (version: string) => {
      const next = new URLSearchParams(params);
      if (activeVersion && version === activeVersion) next.delete("def");
      else next.set("def", version.slice(0, 8));
      setParams(next, { replace: true });
    },
    [params, setParams, activeVersion],
  );
  return { requested, select };
}

export function DefinitionSelect(props: {
  refs: DefinitionRef[];
  value: string | null | undefined;
  activeVersion?: string | null;
  onChange: (version: string) => void;
  label?: string;
}) {
  const id = useId();
  const current = props.refs.find((r) => r.version === props.value);
  return (
    <div className="models-defselect">
      <label htmlFor={id} className="small muted">
        {props.label ?? "Definition of default"}
      </label>
      {props.refs.length > 1 ? (
        <select id={id} value={props.value ?? ""} onChange={(e) => props.onChange(e.target.value)}>
          {props.value && !current && <option value={props.value}>{props.value.slice(0, 8)}</option>}
          {props.refs.map((r) => (
            <option key={r.version} value={r.version}>
              {`${r.short} · ${r.summary}${r.version === props.activeVersion ? " (active)" : ""}`}
            </option>
          ))}
        </select>
      ) : null}
      <DefinitionBadge def={current} version={props.value} />
      {props.value && props.value === props.activeVersion && <Pill tone="accent">active</Pill>}
      {props.value && props.activeVersion && props.value !== props.activeVersion && <Pill tone="warn">not the active definition</Pill>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ query states
export const isNotFound = (e: unknown) => typeof e === "object" && e !== null && (e as { status?: number }).status === 404;

/**
 * Like QueryView, but a 404 renders `notFound` (a designed state) instead of the generic error box, and an optional
 * `header` stays on screen while loading or after an error so the page never loses its title.
 */
export function DetailView<T>(props: {
  query: { data?: T; isLoading: boolean; error: unknown };
  notFound: ReactNode;
  header?: ReactNode;
  loadingHeight?: number;
  children: (data: T) => ReactNode;
}) {
  const { query } = props;
  if (query.isLoading || (!query.error && query.data === undefined)) {
    return (
      <>
        {props.header}
        <Loading height={props.loadingHeight} />
      </>
    );
  }
  if (query.error) {
    return isNotFound(query.error) ? (
      <>{props.notFound}</>
    ) : (
      <>
        {props.header}
        <ErrorState error={query.error} />
      </>
    );
  }
  return <>{props.children(query.data as T)}</>;
}

export function NotFoundState({ title, children, back }: { title: string; children?: ReactNode; back: { to: string; label: string } }) {
  return (
    <EmptyState title={title} action={<Link to={back.to}>{back.label}</Link>}>
      {children}
    </EmptyState>
  );
}

/** Column header text that may wrap onto two lines, so wide tables fit without scrolling. */
export function WrapHeader({ children, title, width = "6rem" }: { children: ReactNode; title?: string; width?: string }) {
  return (
    <span title={title} style={{ display: "inline-block", whiteSpace: "normal", maxWidth: width }}>
      {children}
    </span>
  );
}

/** Wrap links inside a clickable table row so that following the link does not also trigger the row click. */
export function StopRowClick({ children }: { children: ReactNode }) {
  return <span onClick={(e) => e.stopPropagation()}>{children}</span>;
}

// ------------------------------------------------------------------------------------------------ charts
/** Width in pixels of an element, kept current on resize, so an SVG chart can be drawn at 1:1 scale and keep readable text. */
export function useElementWidth<T extends HTMLElement>(fallback = 560): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.round(el.getBoundingClientRect().width));
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(Math.round(entries[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width > 0 ? width : fallback];
}

// ------------------------------------------------------------------------------------------------ bars
export interface HBarRow {
  key: string;
  label: ReactNode;
  value: number;
  /** text shown at the right of the bar (defaults to format(value)) */
  display?: ReactNode;
  note?: ReactNode;
  tone?: "accent" | "good" | "warn" | "crit" | "muted";
}

/**
 * Horizontal bars drawn to scale with the exact value printed beside each bar (pure HTML and CSS).
 * `markers` draw dashed reference lines across every bar (for example a threshold); state what they mean in
 * `footnote` or in the marker labels, which are printed under the bars.
 */
export function HBars(props: {
  title: string;
  rows: HBarRow[];
  format: (v: number) => string;
  min?: number;
  max?: number;
  markers?: { value: number; label: string }[];
  footnote?: ReactNode;
}) {
  const min = props.min ?? 0;
  const max = props.max ?? Math.max(0, ...props.rows.map((r) => r.value), ...(props.markers ?? []).map((m) => m.value));
  const span = max - min;
  const pos = (v: number) => (span > 0 ? Math.max(0, Math.min(100, ((v - min) / span) * 100)) : 0);
  return (
    <div role="group" aria-label={props.title} className="models-hbars-wrap">
      <div className="models-hbars">
        {props.rows.map((r) => (
          <div className="models-hbar" key={r.key}>
            <div className="label">{r.label}</div>
            <div className="track" aria-hidden>
              <div className={`fill ${r.tone ?? ""}`} style={{ width: `${pos(r.value)}%` }} />
              {(props.markers ?? []).map((m, i) => (
                <div key={i} className="tick" style={{ left: `${pos(m.value)}%` }} title={m.label} />
              ))}
            </div>
            <div className="val">{r.display ?? props.format(r.value)}</div>
            {r.note && <div className="note">{r.note}</div>}
          </div>
        ))}
      </div>
      {((props.markers && props.markers.length > 0) || props.footnote) && (
        <div className="models-hbars-foot">
          {props.markers && props.markers.length > 0 && <span>Dashed line: {props.markers.map((m) => `${m.label} (${props.format(m.value)})`).join("; ")}. </span>}
          {props.footnote}
        </div>
      )}
    </div>
  );
}
