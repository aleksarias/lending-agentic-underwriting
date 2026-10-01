/** Tiles, watchlists and the filterable catalog table for one definition of default. Filter state lives in the URL. */
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { CatalogData, Tile } from "../../api/types";
import { fmtNum } from "../../lib/format";
import { plural } from "../Models/shared";
import type { Limits } from "../Performance/thresholds";
import { Card, EmptyState, Section, Tiles } from "../ui";
import { CatalogTable, availabilityLabel, psiBand, sourceLabel } from "./CatalogTable";
import { Watchlists } from "./Watchlists";
import "./data.css";

export function CatalogSection({ c, limits, defShort }: { c: CatalogData; limits: Limits; defShort: string | null }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const leak = params.get("leak") ?? "";
  const proxy = params.get("proxy") ?? "";
  const source = params.get("source") ?? "";
  const prohibitedOnly = params.get("prohibited") === "1";
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const vars = c.variables;
  const sources = useMemo(() => Array.from(new Set(vars.map((v) => v.source_system))).sort(), [vars]);
  const hasProhibited = vars.some((v) => v.prohibited);
  const needle = q.trim().toLowerCase();
  const rows = vars.filter(
    (v) =>
      (!needle || v.variable.toLowerCase().includes(needle) || v.description.toLowerCase().includes(needle) || v.source_system.toLowerCase().includes(needle)) &&
      (!leak || (leak === "risky" ? v.leakage_risk !== "low" : v.leakage_risk === leak)) &&
      (!proxy || v.proxy_risk === proxy) &&
      (!source || v.source_system === source) &&
      (!prohibitedOnly || v.prohibited),
  );
  const filtered = !!(q || leak || proxy || source || prohibitedOnly);

  const numeric = vars.filter((v) => v.dtype === "numeric").length;
  const leakHigh = vars.filter((v) => v.leakage_risk === "high").length;
  const leakMed = vars.filter((v) => v.leakage_risk === "medium").length;
  const proxyHigh = vars.filter((v) => v.proxy_risk === "high").length;
  const alerts = vars.filter((v) => psiBand(v.drift_psi, limits) === "alert").length;
  const warns = vars.filter((v) => psiBand(v.drift_psi, limits) === "warn").length;
  const haveBands = limits.psiAlert != null || limits.psiWarn != null;

  if (vars.length === 0) {
    return (
      <EmptyState title="No catalog for this definition yet">
        The pipeline builds the catalog (statistics, drift, leakage and proxy risk for every variable) each time a definition of default is applied, because a variable’s predictiveness depends on the
        label. Apply the definition with <code>lau default-definition apply</code>, or choose another definition above.
      </EmptyState>
    );
  }

  const tiles: Tile[] = [
    { key: "n", label: "Variables", value: fmtNum(vars.length), sub: `${fmtNum(numeric)} numeric, ${fmtNum(vars.length - numeric)} categorical` },
    { key: "leak", label: "Leakage risk", value: leakHigh ? `${leakHigh} high` : "None high", sub: leakMed ? `${leakMed} medium` : "a high-risk variable fails the leakage check", tone: leakHigh ? "crit" : "good" },
    { key: "proxy", label: "Proxy risk", value: proxyHigh ? `${proxyHigh} flagged` : "None flagged", sub: "could stand in for a protected class", tone: proxyHigh ? "warn" : "good" },
  ];
  if (haveBands) {
    tiles.push({
      key: "drift",
      label: "Drift in the data",
      value: alerts ? `${alerts} large` : warns ? `${warns} moderate` : "None",
      sub: alerts || warns ? `${alerts} large, ${warns} moderate shift${warns === 1 ? "" : "s"} (PSI)` : "no variable moved much between training and validation",
      tone: alerts ? "warn" : null,
    });
  }

  return (
    <>
      <Tiles tiles={tiles} />
      <Watchlists variables={vars} proxyThreshold={limits.proxyAucFlag} defShort={defShort} />

      <Section
        id="catalog"
        title="Catalog"
        note="Statistics are from the training loans under this definition. Univariate AUC is how well the variable alone ranks default; drift PSI is how far its distribution moved between the earliest training months and the validation loans. Click a row for the full profile."
      >
        <div className="models-toolbar" role="group" aria-label="Filter the catalog">
          <label className="field grow">
            Search variables
            <input type="search" value={q} placeholder="Name, description or source" onChange={(e) => setParam("q", e.target.value)} />
          </label>
          <label className="field">
            Leakage risk
            <select value={leak} onChange={(e) => setParam("leak", e.target.value)}>
              <option value="">Any</option>
              <option value="risky">Medium or high</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
          <label className="field">
            Proxy risk
            <select value={proxy} onChange={(e) => setParam("proxy", e.target.value)}>
              <option value="">Any</option>
              <option value="high">Flagged</option>
              <option value="low">Not flagged</option>
            </select>
          </label>
          <label className="field">
            Source
            <select value={source} onChange={(e) => setParam("source", e.target.value)}>
              <option value="">All sources</option>
              {sources.map((s) => (
                <option key={s} value={s}>
                  {sourceLabel(s)} ({vars.filter((v) => v.source_system === s).length})
                </option>
              ))}
            </select>
          </label>
          {hasProhibited && (
            <label className="data-check">
              <input type="checkbox" checked={prohibitedOnly} onChange={(e) => setParam("prohibited", e.target.checked ? "1" : "")} /> Prohibited only
            </label>
          )}
          {filtered && (
            <button className="btn small" type="button" onClick={() => setParams(new URLSearchParams(params.get("def") ? { def: params.get("def") as string } : {}), { replace: true })}>
              Clear filters
            </button>
          )}
          <span className="small muted" aria-live="polite">
            {rows.length === vars.length ? plural(vars.length, "variable") : `${fmtNum(rows.length)} of ${plural(vars.length, "variable")} shown`}
          </span>
        </div>
        {rows.length === 0 ? (
          <EmptyState title="No variable matches these filters">Try a shorter search or clear the risk filters.</EmptyState>
        ) : (
          <Card flush kind="measured">
            <CatalogTable rows={rows} defShort={defShort} limits={limits} />
          </Card>
        )}
        <div className="xs muted">
          “Available at” comes from the field lineage: “{availabilityLabel("decision")}” means the value is known when the lending decision is made, and “{availabilityLabel("unknown")}” means the lineage does
          not record when it becomes available.
        </div>
      </Section>
    </>
  );
}
