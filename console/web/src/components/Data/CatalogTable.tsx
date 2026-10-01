/** The data catalog as a sortable table: type, source, availability, missingness, signal, drift, leakage and proxy risk. */
import { useNavigate } from "react-router-dom";
import type { CatalogVariable } from "../../api/types";
import { fmtAuc, fmtPct, titleCase } from "../../lib/format";
import { classLabel } from "../Fairness/labels";
import { StopRowClick, WrapHeader } from "../Models/shared";
import type { Limits } from "../Performance/thresholds";
import { DataTable, Pill, type Column } from "../ui";
import { variableHref } from "./Watchlists";
import { Link } from "react-router-dom";
import "./data.css";

const RISK_RANK = { high: 3, medium: 2, low: 1 } as const;

const SOURCE_LABEL: Record<string, string> = { crm: "CRM" };
export const sourceLabel = (s: string) => {
  if (!s) return "Unknown";
  if (SOURCE_LABEL[s]) return SOURCE_LABEL[s];
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};
export const availabilityLabel = (a: string) => (a === "decision" ? "At decision" : a ? titleCase(a) : "Unknown");

export function psiBand(v: number | null, limits: Limits): "alert" | "warn" | null {
  if (v == null) return null;
  if (limits.psiAlert != null && v >= limits.psiAlert) return "alert";
  if (limits.psiWarn != null && v >= limits.psiWarn) return "warn";
  return null;
}

export function CatalogTable({ rows, defShort, limits }: { rows: CatalogVariable[]; defShort: string | null; limits: Limits }) {
  const navigate = useNavigate();
  const columns: Column<CatalogVariable>[] = [
    {
      key: "variable",
      header: "Variable",
      render: (v) => (
        <span>
          <StopRowClick>
            <Link className="mono" to={variableHref(v.variable, defShort)}>
              {v.variable}
            </Link>
          </StopRowClick>
          {v.description && <span className="data-desc">{v.description}</span>}
        </span>
      ),
      sort: (v) => v.variable,
    },
    { key: "type", header: "Type", render: (v) => v.dtype, sort: (v) => v.dtype },
    { key: "source", header: "Source", render: (v) => sourceLabel(v.source_system), sort: (v) => v.source_system },
    {
      key: "avail",
      header: <WrapHeader width="5rem">Available at</WrapHeader>,
      render: (v) => (v.availability === "decision" ? <span>{availabilityLabel(v.availability)}</span> : <Pill tone="warn">{availabilityLabel(v.availability)}</Pill>),
      sort: (v) => v.availability,
    },
    { key: "missing", header: "Missing", align: "right", render: (v) => <span className="num">{fmtPct(v.missing_rate, 1)}</span>, sort: (v) => v.missing_rate },
    {
      key: "auc",
      header: <WrapHeader width="5.5rem" title="AUC of this variable alone against default, on the training loans. 0.5 means no signal.">Univariate AUC</WrapHeader>,
      align: "right",
      render: (v) => <span className="num">{fmtAuc(v.univariate_auc_train, 3)}</span>,
      sort: (v) => v.univariate_auc_train,
    },
    {
      key: "psi",
      header: <WrapHeader title="Population stability index of this variable between the earliest training months and the validation loans.">Drift PSI</WrapHeader>,
      align: "right",
      render: (v) => {
        const band = psiBand(v.drift_psi, limits);
        return (
          <span className="num">
            {fmtAuc(v.drift_psi, 3)}
            {band && <span className="models-cell-sub">{band === "alert" ? "large shift" : "moderate shift"}</span>}
          </span>
        );
      },
      sort: (v) => v.drift_psi,
    },
    {
      key: "leak",
      header: <WrapHeader width="5rem">Leakage risk</WrapHeader>,
      render: (v) => <Pill tone={v.leakage_risk === "high" ? "crit" : v.leakage_risk === "medium" ? "warn" : "neutral"}>{v.leakage_risk}</Pill>,
      sort: (v) => RISK_RANK[v.leakage_risk] ?? 0,
    },
    {
      key: "proxy",
      header: <WrapHeader width="5rem">Proxy risk</WrapHeader>,
      render: (v) => (
        <span>
          <Pill tone={v.proxy_risk === "high" ? "warn" : "neutral"}>{v.proxy_risk}</Pill>
          {v.proxy_risk === "high" && (
            <span className="models-cell-sub">
              AUC {fmtAuc(v.proxy_auc, 3)}, {v.proxy_class ? classLabel(v.proxy_class).toLowerCase() : "protected class"}
            </span>
          )}
        </span>
      ),
      sort: (v) => (v.proxy_risk === "high" ? 1 : 0) + (v.proxy_auc ?? 0) / 10,
    },
    {
      key: "prohibited",
      header: "Prohibited",
      render: (v) => (v.prohibited ? <Pill tone="crit">prohibited</Pill> : <span className="muted">no</span>),
      sort: (v) => (v.prohibited ? 1 : 0),
    },
  ];
  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(v) => v.variable}
      initialSort={{ key: "leak", dir: "desc" }}
      onRowClick={(v) => navigate(variableHref(v.variable, defShort))}
      maxHeight={640}
    />
  );
}
