/**
 * Screen 12 — Data catalog and cash flows: what data a model may use and what to watch. Statistics are computed by
 * the pipeline for each definition of default (a variable's predictiveness and leakage risk depend on the label).
 * Cash-flow cohorts are quarterly aggregates; no applicant rows are shown anywhere on this screen.
 */
import { useCashflowCohorts, useCatalog, useDefinitions, useSettings } from "../api/hooks";
import type { CatalogData, DefinitionRef } from "../api/types";
import { CashflowExplorer } from "../components/Data/CashflowExplorer";
import { CatalogSection } from "../components/Data/CatalogSection";
import { ParitySection } from "../components/Data/ParitySection";
import "../components/Data/data.css";
import { DefinitionSelect, definitionRefOf, pickDefinition, plural, useDefinitionParam } from "../components/shared";
import { limitsFrom } from "../components/Performance/thresholds";
import { Page, PageHeader, QueryView } from "../components/ui";

export default function Data() {
  const defs = useDefinitions();
  const active = defs.data?.find((d) => d.is_active);
  const { requested, select } = useDefinitionParam(active?.version);
  const catalog = useCatalog(requested);
  const cash = useCashflowCohorts();
  const settings = useSettings();
  const limits = limitsFrom(settings.data);

  const refs: DefinitionRef[] = catalog.data?.definitions ?? (defs.data ?? []).map(definitionRefOf);
  const current = pickDefinition(refs, requested, active?.version);

  return (
    <Page>
      <PageHeader
        eyebrow="Data and feedback"
        title="Data catalog"
        summary={catalog.data ? summarySentence(catalog.data, current) : undefined}
        actions={
          <>
            <DefinitionSelect refs={refs} value={catalog.data?.definition_version ?? current?.version} activeVersion={active?.version} onChange={select} />
            <span className="small muted">
              Jump to:{" "}
              {catalog.data && catalog.data.variables.length > 0 && (
                <>
                  <a href="#watchlists">watchlists</a> · <a href="#catalog">catalog table</a> ·{" "}
                </>
              )}
              <a href="#cashflow">cash-flow cohorts</a> · <a href="#parity">training and serving parity</a>
            </span>
          </>
        }
      />
      <QueryView query={catalog} loadingHeight={360}>
        {(c) => <CatalogSection c={c} limits={limits} defShort={c.definition_version === active?.version ? null : c.definition_version.slice(0, 8)} />}
      </QueryView>
      <QueryView query={cash} loadingHeight={240}>
        {(d) => <CashflowExplorer data={d} />}
      </QueryView>
      <ParitySection />
    </Page>
  );
}

function summarySentence(c: CatalogData, def: DefinitionRef | undefined): string {
  const d = def?.summary ?? "this definition";
  const v = c.variables;
  if (v.length === 0) return `No catalog has been built for ${d} yet.`;
  const high = v.filter((x) => x.leakage_risk === "high").length;
  const proxies = v.filter((x) => x.proxy_risk === "high").length;
  const prohibited = v.filter((x) => x.prohibited).length;
  return `${plural(v.length, "variable")} for ${d}: ${high ? `${high} with high leakage risk` : "none with high leakage risk"} and ${proxies ? `${proxies} flagged as ${proxies === 1 ? "a proxy" : "proxies"} for a protected class` : "none flagged as proxies for a protected class"}; ${
    prohibited ? `${prohibited} ${prohibited === 1 ? "is" : "are"} on the prohibited register` : "none is on the prohibited register"
  }.`;
}
