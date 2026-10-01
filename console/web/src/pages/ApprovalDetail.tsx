/**
 * Screen 15 (detail) — the evidence packet: the decision screen for one candidate.
 *
 * Everything a person needs before deciding is on this page, in the order a reviewer reads it: the answer and what
 * blocks it, the harness's measurements (validation, checks, benchmark position, holdout gate), the agents' claims
 * (red-team and compliance reports, marked proposed), fairness and cost, and the three steps to act: run the holdout
 * gate, approve or reject with a rationale, promote. Nothing here changes anything until a confirmed action completes.
 */
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useApprovals, useCycles, useEvidence, usePerformance, useRollouts, useStatus } from "../api/hooks";
import type { EvidencePacket } from "../api/types";
import { BenchmarkSection, useBenchmarkPosition } from "../components/ApprovalDetail/BenchmarkSection";
import { DecisionSteps } from "../components/ApprovalDetail/DecisionSteps";
import { ACTIONS_DISABLED, deriveFlow, stepViews } from "../components/ApprovalDetail/derive";
import { FairnessCostSection } from "../components/ApprovalDetail/FairnessCostSection";
import { GateSection, type HoldoutBudget } from "../components/ApprovalDetail/GateSection";
import { ReferencesSection } from "../components/ApprovalDetail/ReferencesSection";
import { ReportsSection } from "../components/ApprovalDetail/ReportsSection";
import { packetSummary } from "../components/ApprovalDetail/summary";
import { ValidationSection } from "../components/ApprovalDetail/ValidationSection";
import "../components/ApprovalDetail/ApprovalDetail.css";
import { DefBadge, useDefinitionRefs } from "../components/Operate/definitions";
import { useResolvedModel } from "../components/Operate/models";
import { useThresholds } from "../components/Operate/thresholds";
import { Banner, Card, DefinitionBadge, EmptyState, KeyValue, ModelBadge, Page, PageHeader, QueryView, Section, TimeAgo, links } from "../components/ui";
import { refLabel } from "../lib/format";

export default function ApprovalDetail() {
  const { candidateRef } = useParams();
  const q = useEvidence(candidateRef);
  if (q.error instanceof ApiError && q.error.status === 404) {
    return (
      <Page>
        <PageHeader eyebrow="Decide and operate" title="Evidence packet" summary={`There is no evidence for ${refLabel(candidateRef)}.`} />
        <EmptyState
          title="No evaluation for this candidate"
          action={
            <Link className="btn small" to="/approvals">
              Back to approvals
            </Link>
          }
        >
          An evidence packet exists once the harness has evaluated a candidate. Check the reference, or pick a candidate from the approvals list.
        </EmptyState>
      </Page>
    );
  }
  return (
    <Page>
      <QueryView query={q} loadingHeight={360}>
        {(p) => <Packet p={p} />}
      </QueryView>
    </Page>
  );
}

function Packet({ p }: { p: EvidencePacket }) {
  const status = useStatus();
  const perf = usePerformance(p.definition_version);
  const approvals = useApprovals();
  const rollouts = useRollouts();
  const cycles = useCycles();
  const thresholds = useThresholds();
  const findDefinition = useDefinitionRefs();
  const model = useResolvedModel(p.model);
  const pos = useBenchmarkPosition(p);

  const definition = findDefinition(p.definition_version);
  const definitionLabel = definition ? `${p.definition_version.slice(0, 8)} (${definition.summary})` : p.definition_version.slice(0, 8);
  // the packet itself lists "Actions are disabled" as a blocker when they are, so it can answer before the status loads
  const actionsEnabled = status.data?.actions_enabled ?? !p.blockers.includes(ACTIONS_DISABLED);
  const activeDefinition = status.data?.active_definition?.version ?? null;
  const holdout: HoldoutBudget | null = perf.data ? { used: perf.data.holdout.used, budget: perf.data.holdout.budget } : null;

  const flow = deriveFlow(p, approvals.data?.history, rollouts.data?.promotions);
  const steps = stepViews(p, flow, actionsEnabled);
  const currentChampion = rollouts.data?.promotions.find((x) => x.definition_version === p.definition_version) ?? null;

  const newestReport = [...p.reports].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const cycleId = newestReport?.cycle_id ?? null;
  const cycle = cycleId ? cycles.data?.find((c) => c.cycle_id === cycleId) : undefined;

  // "Already promoted." is how the API words a promotion; it is shown as the outcome, not as something in the way
  const promoted = flow.promotion;
  const blockers = promoted ? flow.candidateBlockers.filter((b) => b !== "Already promoted.") : flow.candidateBlockers;
  const superseded = !!activeDefinition && p.definition_version !== activeDefinition;

  return (
    <>
      <PageHeader
        eyebrow="Decide and operate"
        title={`Evidence packet: ${p.model.label}`}
        summary={packetSummary(p, pos, flow, steps, actionsEnabled)}
        meta={
          <>
            <span>Definition of default</span>
            <DefBadge version={p.definition_version} />
          </>
        }
        actions={
          <Link className="btn small" to="/approvals">
            All approvals
          </Link>
        }
      />

      {flow.decision?.decision === "reject" && !promoted && (
        <Banner tone="warn" title={`${p.model.label} was rejected`}>
          Rejected by {flow.decision.approver || "an unnamed approver"} <TimeAgo iso={flow.decision.ts} />. From this console a rejection is final for the candidate: it cannot be promoted, and a new
          candidate would be needed.
        </Banner>
      )}
      {promoted && (
        <Banner tone="good" title={`${p.model.label} was promoted as production v${promoted.production_model_version}`}>
          {promoted.serving ? "It holds the serving alias." : "It is champion for its definition but not serving."} See <Link to="/rollouts">Rollouts</Link> for the record.
        </Banner>
      )}
      {blockers.length > 0 ? (
        <Banner tone="warn" title={`${blockers.length === 1 ? "A blocker stands" : `${blockers.length} blockers stand`} in the way of promoting ${p.model.label}`}>
          <ul className="approvaldetail-blockers">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </Banner>
      ) : promoted || flow.decision ? null : (
        <Banner tone="neutral" title="No blockers recorded">
          The API lists nothing that stops this candidate. The three steps on this page still have to be completed, in order.
        </Banner>
      )}

      {superseded && (
        <Banner tone="warn" title="This candidate belongs to a definition that is no longer active">
          It was evaluated under {definitionLabel}; the active definition is {status.data?.active_definition?.summary ?? activeDefinition?.slice(0, 8)}. Promoting it would make
          it champion for its own definition, but it could never serve.
        </Banner>
      )}

      <div className="approvaldetail-layout">
        <div className="approvaldetail-main">
          <Section title="Model and definition">
            <Card>
              <KeyValue
                items={[
                  ["Candidate", <span key="c" className="row" style={{ gap: 8 }}>
                    <ModelBadge model={model} />
                    <span className="mono xs muted">{p.candidate_ref}</span>
                  </span>],
                  ["Definition of default", <DefinitionBadge key="d" def={definition} version={p.definition_version} />],
                  [
                    "Proposed by cycle",
                    cycleId ? (
                      <Link key="y" to={links.cycle(cycleId)} className="mono">
                        {cycleId}
                      </Link>
                    ) : (
                      <span className="muted">not known</span>
                    ),
                  ],
                ]}
              />
              <div className="xs muted" style={{ marginTop: 8 }}>
                Every measurement on this page is under this definition of default. Models trained under another definition are compared only in the benchmark
                section, where all of them are re-scored under the same frozen benchmark definitions.
              </div>
            </Card>
          </Section>

          <ValidationSection p={p} />
          <BenchmarkSection p={p} pos={pos} />
          <GateSection p={p} holdout={holdout} />
          <ReportsSection reports={p.reports} />
          <FairnessCostSection p={p} minAirLimit={thresholds.minAir} cycle={{ cycleId, anthropicUsd: cycle?.anthropic_usd ?? null }} />
        </div>

        <DecisionSteps
          packet={p}
          flow={flow}
          actionsEnabled={actionsEnabled}
          user={status.data?.user ?? null}
          holdout={holdout}
          definitionLabel={definitionLabel}
          activeDefinition={activeDefinition}
          apiLive={status.data?.api.live ?? false}
          currentChampion={currentChampion}
          historyUnavailable={!!approvals.error || !!rollouts.error}
        />
      </div>

      <ReferencesSection p={p} decision={flow.decision} promotion={flow.promotion} />
    </>
  );
}
