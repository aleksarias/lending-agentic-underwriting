/** Features lab content: summary tiles, filters (status, risk, text; all in the query string) and the table. */
import type { DefinitionRef, FeatureRow, Tile } from "../../api/types";
import { fmtAuc } from "../../lib/format";
import { Banner, Card, EmptyState, PageHeader, Section, Tiles } from "../ui";
import { DefBadge, FilterSelect, UrlSearch, useUrlFilters } from "../Agents/shared";
import { FeatureTable } from "./FeatureTable";
import { HypothesesSection } from "./PeopleInput";

const KEYS = ["status", "risk", "q"] as const;

type Perf = FeatureRow["performance"][string] | undefined;
const leaky = (p: Perf) => p?.leakage_risk === "medium" || p?.leakage_risk === "high";
const proxy = (p: Perf) => p?.proxy_risk === "high";

const RISK_OPTIONS = [
  { value: "", label: "Any" },
  { value: "flagged", label: "Any risk flagged" },
  { value: "leakage", label: "Leakage risk: medium or high" },
  { value: "proxy", label: "Proxy risk: high" },
  { value: "clean", label: "Screened, nothing flagged" },
  { value: "unscreened", label: "Not screened under this definition" },
];

function matchesRisk(risk: string, p: Perf): boolean {
  switch (risk) {
    case "flagged":
      return leaky(p) || proxy(p);
    case "leakage":
      return leaky(p);
    case "proxy":
      return proxy(p);
    case "clean":
      return !!p && !leaky(p) && !proxy(p);
    case "unscreened":
      return !p;
    default:
      return true;
  }
}

export function featuresSentence(features: FeatureRow[], active: DefinitionRef | null): string {
  if (!features.length) return "No agent has proposed an engineered feature yet.";
  const v = active?.version ?? "";
  const screened = features.filter((f) => f.performance[v]);
  const here = features.filter((f) => f.created_under_definition === v).length;
  const used = features.filter((f) => f.used_in.length).length;
  const flagged = screened.filter((f) => leaky(f.performance[v]) || proxy(f.performance[v])).length;
  // the "best" is picked among features with no risk flag, so a leaky feature never reads as the strongest
  const clean = screened.filter((f) => !leaky(f.performance[v]) && !proxy(f.performance[v]) && f.performance[v].auc != null);
  const best = [...clean].sort((a, b) => (b.performance[v].auc ?? 0) - (a.performance[v].auc ?? 0))[0];
  const parts = [`Agents have proposed ${features.length} engineered features${active ? `; ${here} were created under the active definition (${active.summary})` : ""}.`];
  parts.push(`${used} ${used === 1 ? "is" : "are"} used in an evaluated model, and ${flagged === 0 ? "none is" : `${flagged} ${flagged === 1 ? "is" : "are"}`} flagged for leakage or proxy risk.`);
  if (best) parts.push(`The highest univariate AUC among features with no risk flag is ${fmtAuc(best.performance[v].auc, 3)} (${best.name}), the best of ${clean.length} screened.`);
  return parts.join(" ");
}

export function FeaturesView({ features, active, initialQuery }: { features: FeatureRow[]; active: DefinitionRef | null; initialQuery: string }) {
  const f = useUrlFilters(KEYS);
  const v = active?.version ?? "";
  const statuses = [...new Set(features.map((x) => x.status))];

  const matches = (x: FeatureRow, skip?: (typeof KEYS)[number]) => {
    const p = x.performance[v];
    if (skip !== "status" && f.values.status && x.status !== f.values.status) return false;
    if (skip !== "risk" && !matchesRisk(f.values.risk, p)) return false;
    if (skip !== "q" && f.values.q.trim()) {
      const q = f.values.q.trim().toLowerCase();
      const hay = `${x.name} ${x.hypothesis} ${x.rationale} ${x.expression} ${x.author} ${x.cycle_id}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  };
  const rows = features.filter((x) => matches(x));

  const screened = features.filter((x) => x.performance[v]).length;
  const tiles: Tile[] = [
    { key: "all", label: "Proposed by agents", value: String(features.length), sub: "every engineered feature in the registry" },
    { key: "here", label: "Screened under this definition", value: `${screened} of ${features.length}`, sub: active?.summary ?? "no active definition" },
    { key: "used", label: "Used in an evaluated model", value: String(features.filter((x) => x.used_in.length).length), sub: "latest evaluation of each model" },
    {
      key: "risk",
      label: "Flagged for leakage or proxy risk",
      value: String(features.filter((x) => leaky(x.performance[v]) || proxy(x.performance[v])).length),
      sub: "under this definition",
      tone: features.some((x) => leaky(x.performance[v]) || proxy(x.performance[v])) ? "warn" : null,
    },
  ];

  const header = (
    <PageHeader
      eyebrow="Data and feedback"
      title="Features lab"
      summary={featuresSentence(features, active)}
      meta={
        <>
          <span>Definition of default</span>
          <DefBadge version={active?.version ?? null} />
        </>
      }
    />
  );

  if (features.length === 0) {
    return (
      <>
        {header}
        <EmptyState title="No features have been proposed yet">
          The feature agent proposes engineered features as SQL expressions during an improvement cycle. Each one appears here with its screen results under the active definition.
        </EmptyState>
        <HypothesesSection />
      </>
    );
  }

  return (
    <>
      {header}
      {!active && (
        <Banner tone="warn" title="No active definition">
          <span className="small">Without an active definition there are no screen results to show; the list below is every feature that has been proposed.</span>
        </Banner>
      )}
      <Tiles tiles={tiles} />

      <Section
        title="Engineered features"
        note="Agents propose features as SQL expressions. The pipeline screens each one on training loans under the active definition: AUC of the feature alone, share missing, leakage and proxy flags. The screen is not validation evidence and does not count as a validation test. Select a feature name to see its SQL and the agent's reasoning."
      >
        <Card>
          <div className="row" style={{ alignItems: "flex-end", gap: 14 }}>
            <FilterSelect
              label="Status"
              value={f.values.status}
              onChange={(x) => f.set("status", x)}
              options={[
                { value: "", label: `All (${features.filter((x) => matches(x, "status")).length})` },
                ...statuses.map((s) => ({ value: s, label: `${s} (${features.filter((x) => matches(x, "status") && x.status === s).length})` })),
              ]}
            />
            <FilterSelect label="Risk under this definition" value={f.values.risk} onChange={(x) => f.set("risk", x)} options={RISK_OPTIONS} />
            <UrlSearch label="Search name, SQL, hypothesis or cycle" value={f.values.q} onChange={(x) => f.set("q", x)} placeholder="for example liquidity or cf_" />
            {f.active && (
              <button type="button" className="btn small" onClick={f.clear}>
                Clear filters
              </button>
            )}
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>
            Showing {rows.length} of {features.length} features.
          </div>
        </Card>
        <FeatureTable rows={rows} activeVersion={v} initiallyOpen={initialQuery && features.some((x) => x.name === initialQuery) ? [initialQuery] : []} />
      </Section>
      <HypothesesSection />
    </>
  );
}
