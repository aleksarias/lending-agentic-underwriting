/**
 * Screen 6 — Definitions over time: which definition of default is active, how it has changed, and how much the
 * definition (rather than the portfolio) moves the default rate.
 *
 * A definition decides what counts as a default, so every label, model and metric depends on it. Changing it is a
 * person's decision with an approval; this screen shows each version, who activated it and when, what changed in it, and
 * the default rate under 30, 60 and 90 days past due by origination quarter.
 */
import { Link } from "react-router-dom";
import { useDefinitions, usePipeline, useSensitivity } from "../api/hooks";
import type { DefinitionVersion } from "../api/types";
import { ActiveBanner } from "../components/Definitions/ActiveBanner";
import "../components/Definitions/Definitions.css";
import { FieldChanges } from "../components/Definitions/FieldChanges";
import { ProposalSection } from "../components/Definitions/ProposalSection";
import { SensitivitySection } from "../components/Definitions/SensitivitySection";
import { VersionHistory } from "../components/Definitions/VersionHistory";
import { definitionLabel, definitionRefOf, neighbours } from "../components/Definitions/labels";
import { StageList } from "../components/lists";
import { Card, DefinitionBadge, Page, PageHeader, QueryView, Section } from "../components/ui";
import { fmtDate, fmtNum, fmtPct } from "../lib/format";

export default function Definitions() {
  const definitions = useDefinitions();
  return (
    <Page>
      <QueryView query={definitions} loadingHeight={360}>
        {(defs) => <DefinitionsBody defs={defs} />}
      </QueryView>
    </Page>
  );
}

function DefinitionsBody({ defs }: { defs: DefinitionVersion[] }) {
  const sensitivity = useSensitivity();
  const active = defs.find((d) => d.is_active);
  return (
    <>
      <PageHeader
        eyebrow="Over time"
        title="Definitions of default"
        summary={summarise(defs, active)}
        meta={
          <>
            <span>Definition of default now</span>
            {active ? <DefinitionBadge def={definitionRefOf(active)} /> : <span>none active</span>}
            <span>· all times UTC</span>
          </>
        }
      />

      <ActiveBanner active={active} hasAny={defs.length > 0} />
      <ProposalSection />

      {defs.length > 0 && (
        <>
          <Section
            title="Version history"
            note="Every recorded version, with the period it was active and the labels it produced. The default rates are counts of labelled loans under each definition; they say how strict a definition is, not how well a model performs."
          >
            <Card flush kind="measured">
              <VersionHistory defs={defs} />
            </Card>
          </Section>

          <Section
            title="Definition sensitivity"
            note="How the default rate depends on the definition: the same loans, counted under 30, 60 and 90 days past due."
            right={active ? <DefinitionBadge def={definitionRefOf(active)} /> : undefined}
          >
            <QueryView query={sensitivity} loadingHeight={300}>
              {(data) => <SensitivitySection data={data} active={active} />}
            </QueryView>
          </Section>

          <Section
            title="What changed in each version"
            note="Field changes against the definition that was active before it. Only fields that affect the labels are listed; a change to a name or description does not count."
          >
            <FieldChanges defs={defs} />
          </Section>

          {active && <ActivePipeline active={active} />}
        </>
      )}
    </>
  );
}

/** Freshness of every pipeline stage for the active definition. */
function ActivePipeline({ active }: { active: DefinitionVersion }) {
  const pipeline = usePipeline();
  return (
    <Section
      title="Pipeline freshness for the active definition"
      note="The stages that rebuild data, labels, baselines and monitoring whenever the definition changes."
      right={
        <Link className="small" to={`/definitions/${active.version}`}>
          Stages and runs for this definition
        </Link>
      }
    >
      <QueryView query={pipeline} loadingHeight={200}>
        {(p) => {
          const notFresh = p.stages.filter((s) => s.status !== "fresh").length;
          return (
            <Card>
              <div className="row between small muted definitions-wrap" style={{ marginBottom: 6 }}>
                <span>{p.stages.length === 0 ? "No stages" : notFresh ? `${notFresh} of ${p.stages.length} stages not fresh` : "All stages fresh"}</span>
                {p.definition_version && <DefinitionBadge version={p.definition_version} def={p.definition_version === active.version ? definitionRefOf(active) : null} />}
              </div>
              <StageList stages={p.stages} />
            </Card>
          );
        }}
      </QueryView>
    </Section>
  );
}

/** One plain-language sentence: which definition is active since when, what it replaced, and what it labels. */
function summarise(defs: DefinitionVersion[], active: DefinitionVersion | undefined): string {
  if (defs.length === 0) return "No definition of default has been recorded yet, so no loan can be labelled as a default.";
  if (!active) return `${defs.length} definition${defs.length === 1 ? " is" : "s are"} recorded but none is active, so no loan can be labelled as a default.`;
  const { previous } = neighbours(defs, active.version);
  const stats = active.label_stats;
  const since = active.active_from ? ` since ${fmtDate(active.active_from)}` : "";
  const replaced = previous ? `, replacing ${definitionLabel(previous)}` : "";
  const labelled = stats ? `; ${fmtNum(stats.n_default)} of ${fmtNum(stats.n_eligible)} eligible loans (${fmtPct(stats.default_rate)}) default under it` : "";
  return `${definitionLabel(active)} has been the definition of default${since}${replaced}${labelled}.`;
}
