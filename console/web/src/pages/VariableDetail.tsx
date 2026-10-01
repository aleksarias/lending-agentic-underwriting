/**
 * Screen 12, detail — one catalog variable: where it comes from, how complete and stable it is, how it is
 * distributed, and whether the leakage, proxy or prohibited screens stop a candidate from using it. Statistics are
 * per definition of default (a variable's predictiveness and leakage risk depend on the label).
 */
import { Link, useParams } from "react-router-dom";
import { useDefinitions, useSettings, useVariable } from "../api/hooks";
import type { CatalogVariable, DefinitionRef, Tile } from "../api/types";
import { psiBand, sourceLabel } from "../components/Data/CatalogTable";
import { classLabel } from "../components/Fairness/labels";
import { DefinitionSelect, DetailView, NotFoundState, definitionRefOf, pickDefinition, useDefinitionParam } from "../components/Models/shared";
import { limitsFrom, type Limits } from "../components/Performance/thresholds";
import { Distribution } from "../components/VariableDetail/Distribution";
import { RiskScreens } from "../components/VariableDetail/RiskScreens";
import "../components/VariableDetail/variable.css";
import { Card, KeyValue, Page, PageHeader, Section, Tiles } from "../components/ui";
import { fmtAuc, fmtNum, fmtPct } from "../lib/format";

export default function VariableDetail() {
  const { variable } = useParams();
  const defs = useDefinitions();
  const active = defs.data?.find((d) => d.is_active);
  const { requested, select } = useDefinitionParam(active?.version);
  const v = useVariable(variable, requested);
  const settings = useSettings();
  const limits = limitsFrom(settings.data);

  const refs: DefinitionRef[] = (defs.data ?? []).map(definitionRefOf);
  const current = pickDefinition(refs, requested, active?.version);
  const back = `/data${current && current.version !== active?.version ? `?def=${current.short}` : ""}`;

  return (
    <Page>
      <PageHeader
        eyebrow="Data and feedback"
        title={variable ?? "Variable"}
        summary={v.data ? summarySentence(v.data, limits) : undefined}
        meta={<Link to={back}>All variables</Link>}
        actions={<DefinitionSelect refs={refs} value={current?.version} activeVersion={active?.version} onChange={select} />}
      />
      <DetailView
        query={v}
        loadingHeight={300}
        notFound={
          <NotFoundState title="No such variable in this catalog" back={{ to: back, label: "Back to the catalog" }}>
            <code>{variable}</code> is not in the data catalog{current ? ` for ${current.summary}` : ""}. The catalog is built for each definition of default, so a variable that exists under another
            definition may be missing here. Choose another definition above, or check the name.
          </NotFoundState>
        }
      >
        {(x) => (
          <>
            <Tiles tiles={tiles(x, limits)} />
            <RiskScreens x={x} limits={limits} />
            <Section title="Description">
              <Card>
                <KeyValue
                  items={[
                    ["Description", x.description || <span className="muted">none recorded</span>],
                    ["Source system", sourceLabel(x.source_system)],
                    ["Type", x.dtype],
                  ]}
                />
              </Card>
            </Section>
            <Distribution x={x} />
          </>
        )}
      </DetailView>
    </Page>
  );
}

function tiles(x: CatalogVariable, limits: Limits): Tile[] {
  const band = psiBand(x.drift_psi, limits);
  return [
    { key: "auc", label: "Univariate AUC", value: fmtAuc(x.univariate_auc_train, 3), sub: "alone against default, training loans; 0.5 is no signal" },
    { key: "missing", label: "Missing", value: fmtPct(x.missing_rate, 1), sub: "share of applications without a value" },
    {
      key: "psi",
      label: "Drift PSI",
      value: fmtAuc(x.drift_psi, 3),
      sub: band ? `${band === "alert" ? "large" : "moderate"} shift between the earliest training months and validation` : "between the earliest training months and validation",
      tone: band === "alert" ? "warn" : null,
    },
    { key: "card", label: "Distinct values", value: fmtNum(x.cardinality), sub: `${x.dtype} variable` },
  ];
}

function summarySentence(x: CatalogVariable, limits: Limits): string {
  const flags: string[] = [];
  if (x.leakage_risk === "high") flags.push(`it has high leakage risk (${x.leakage_reasons || "no reason recorded"}), so a candidate that uses it fails the leakage check`);
  else if (x.leakage_risk === "medium") flags.push(`it has medium leakage risk (${x.leakage_reasons || "no reason recorded"})`);
  if (x.proxy_risk === "high") flags.push(`it is flagged as a proxy for ${x.proxy_class ? classLabel(x.proxy_class).toLowerCase() : "a protected class"} (proxy AUC ${fmtAuc(x.proxy_auc, 3)})`);
  if (x.prohibited) flags.push("it is on the prohibited register");
  if (psiBand(x.drift_psi, limits) === "alert") flags.push(`its distribution has shifted a lot (PSI ${fmtAuc(x.drift_psi, 3)})`);
  const what = x.description ? `${x.description.charAt(0).toUpperCase()}${x.description.slice(1)}` : "Catalog variable";
  const base = `${what}: a ${x.dtype} variable (source: ${sourceLabel(x.source_system)}), ${fmtPct(x.missing_rate, 1)} missing`;
  return flags.length ? `${base}; ${flags.join(", and ")}.` : `${base}; no leakage, proxy or prohibited flag.`;
}
