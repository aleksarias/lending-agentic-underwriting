/**
 * One version of the definition of default: what it means in plain language, when it was active and who approved it,
 * every field, what it does to the loan book (labels, exclusions, triggers), how the loans are split in time, what
 * changed from the version before, and the state of the pipeline that builds its labels.
 */
import { Link, useParams } from "react-router-dom";
import { useDefinition, useDefinitions } from "../api/hooks";
import type { DefinitionVersion } from "../api/types";
import { aroundActivation, compareHref } from "../components/Compare/instants";
import { FieldDiffTable } from "../components/Definitions/FieldDiffTable";
import { definitionLabel, neighbours } from "../components/Definitions/labels";
import "../components/Definitions/Definitions.css";
import { FieldsCard } from "../components/DefinitionDetail/FieldsCard";
import { LabelStatsSection } from "../components/DefinitionDetail/LabelStatsSection";
import { PipelineSection } from "../components/DefinitionDetail/PipelineSection";
import { SplitsSection } from "../components/DefinitionDetail/SplitsSection";
import "../components/DefinitionDetail/DefinitionDetail.css";
import { isMissing } from "../components/History/notFound";
import { Banner, Card, EmptyState, ErrorState, KeyValue, Page, PageHeader, Pill, QueryView, Section } from "../components/ui";
import { fmtDateTime, fmtNum, fmtPct } from "../lib/format";

export default function DefinitionDetail() {
  const { version } = useParams();
  const query = useDefinition(version);
  return (
    <Page>
      {query.error ? (
        <Unavailable version={version} error={query.error} retry={() => void query.refetch()} />
      ) : (
        <QueryView query={query} loadingHeight={360}>
          {(def) => <DefinitionBody def={def} />}
        </QueryView>
      )}
    </Page>
  );
}

/** The definition cannot be shown: the version is unknown (say so, and point back to the list) or the API failed (offer a retry). */
function Unavailable({ version, error, retry }: { version: string | undefined; error: unknown; retry: () => void }) {
  const back = (
    <Link className="btn" to="/definitions">
      Back to Definitions
    </Link>
  );
  if (isMissing(error)) {
    return (
      <>
        <PageHeader eyebrow="Over time" title="Definition" summary="No definition of default with this version is recorded." />
        <EmptyState title="Definition not found" action={back}>
          There is no definition <code>{version}</code>. A version is the first 8 or 12 characters of a definition's content hash; every recorded version is listed on the
          Definitions screen.
        </EmptyState>
      </>
    );
  }
  return (
    <>
      <PageHeader eyebrow="Over time" title="Definition" summary="This definition could not be loaded." />
      <ErrorState error={error} />
      <div className="row">
        {back}
        <button type="button" className="btn" onClick={retry}>
          Try again
        </button>
      </div>
    </>
  );
}

function DefinitionBody({ def }: { def: DefinitionVersion }) {
  const list = useDefinitions();
  const all = list.data ?? [];
  const { previous, next } = neighbours(all, def.version);
  const label = definitionLabel(def);
  const switchRange = def.active_from && previous ? aroundActivation(def.active_from) : null;

  return (
    <>
      <PageHeader
        eyebrow="Over time"
        title={`Definition ${def.short}`}
        summary={summarise(def, label)}
        meta={
          <>
            {/* The badge component always links; on this page that link would point at the page itself. */}
            <span className="badge">
              <span className="mono">{def.short}</span>
              <span>{label}</span>
            </span>
            {def.is_active ? (
              <Pill tone="accent" dot>
                Active now
              </Pill>
            ) : (
              <Pill tone="neutral">{def.active_from ? "Replaced" : "Never activated"}</Pill>
            )}
            <span>· all times UTC</span>
          </>
        }
        actions={
          <>
            <Link className="btn" to="/definitions">
              All definitions
            </Link>
            {previous && (
              <Link className="btn" to={`/definitions/${previous.version}`}>
                Previous: {definitionLabel(previous)}
              </Link>
            )}
            {next && (
              <Link className="btn" to={`/definitions/${next.version}`}>
                Next: {definitionLabel(next)}
              </Link>
            )}
          </>
        }
      />

      <Banner tone={def.is_active ? "accent" : "neutral"} title="What this definition means">
        <div className="definition-detail-wrap stack" style={{ gap: 10 }}>
          <p style={{ margin: "4px 0 0", maxWidth: "90ch" }}>{def.plain_language}</p>
          {def.description && <div className="small muted">Description in the definition file: {def.description}</div>}
          <KeyValue
            items={[
              ["Active from", def.active_from ? fmtDateTime(def.active_from) : <span className="muted">never activated</span>],
              ["Active to", def.is_active ? "still active" : def.active_to ? fmtDateTime(def.active_to) : <span className="muted">not applicable</span>],
              ["Activated by", def.activated_by ?? <span className="muted">not recorded</span>],
              [
                "Approval",
                def.approval_id ? (
                  <span className="row" style={{ gap: 10 }}>
                    <code className="mono">{def.approval_id}</code>
                    <Link className="small" to={`/history?types=approval&definition=${encodeURIComponent(def.version)}`}>
                      Approval events
                    </Link>
                  </span>
                ) : (
                  <span className="muted">no approval id recorded</span>
                ),
              ],
              ["Name in the definition file", <code key="n" className="mono">{def.name}</code>],
              ["Full version", <code key="v" className="mono">{def.version}</code>],
              ["Recorded", def.created_at ? fmtDateTime(def.created_at) : <span className="muted">not recorded</span>],
            ]}
          />
        </div>
      </Banner>

      <Section title="Every field" note="The definition as stored. Any change to one of these fields is a new version with its own hash.">
        <Card flush>
          <FieldsCard def={def} />
        </Card>
      </Section>

      <Section
        title="What it does to the loan book"
        note="Loans are counted once: a loan is either excluded for one reason or eligible, and every default is credited to the first event that caused it."
      >
        <LabelStatsSection def={def} />
      </Section>

      <Section title="Time splits" note="How the labelled loans are divided by origination month.">
        <SplitsSection def={def} />
      </Section>

      <Section
        title={previous ? `Changes from ${definitionLabel(previous)}` : "Changes from the previous version"}
        right={
          switchRange ? (
            <Link className="small" to={compareHref(switchRange.from, switchRange.to)}>
              Everything that changed at the switch
            </Link>
          ) : undefined
        }
      >
        {!def.active_from ? (
          <EmptyState title="Never activated">This version has not been activated, so there is no earlier version to compare it with.</EmptyState>
        ) : !previous ? (
          <EmptyState title="The first recorded definition">Nothing was active before it, so there are no changes to show.</EmptyState>
        ) : def.diff_vs_previous.length === 0 ? (
          <EmptyState title="No field differs">
            The fields match the previous version ({previous.short}). Only the name or description changed, which does not affect any label.
          </EmptyState>
        ) : (
          <FieldDiffTable diffs={def.diff_vs_previous} />
        )}
      </Section>

      <Section title="Pipeline for this definition" note="Stages that build this definition's labels, splits, baselines and monitoring, and its recent runs.">
        <PipelineSection def={def} all={all} />
      </Section>
    </>
  );
}

/** One plain-language sentence: when this version was active and what it labels. */
function summarise(def: DefinitionVersion, label: string): string {
  const period = !def.active_from
    ? `${label} is recorded but has never been activated`
    : def.is_active
      ? `${label} has been active since ${fmtDateTime(def.active_from)}`
      : `${label} was active from ${fmtDateTime(def.active_from)} to ${def.active_to ? fmtDateTime(def.active_to) : "an unrecorded time"}`;
  const s = def.label_stats;
  const labelled = s ? `; ${fmtNum(s.n_default)} of ${fmtNum(s.n_eligible)} eligible loans (${fmtPct(s.default_rate)}) default under it` : "; no labels have been built for it yet";
  return `${period}${labelled}.`;
}
