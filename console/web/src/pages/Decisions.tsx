/**
 * Screen 3 — Decisions: what is the real-time decision API doing?
 *
 * The API is not deployed, so the live section is an Unavailable payload. The screen says plainly what is missing and
 * what it needs, shows what it will contain, and previews the response the endpoint will return (labeled as an
 * illustrative example). It never shows a number that did not come from a real decision.
 */
import { Link } from "react-router-dom";
import { useDecisions, useStatus } from "../api/hooks";
import type { DecisionsData, StatusSummary } from "../api/types";
import { isUnavailable } from "../api/types";
import { ExampleDecision } from "../components/Decisions/ExampleDecision";
import { NotBuiltPanel, type WillShow } from "../components/Operate/NotBuiltPanel";
import { Card, EmptyState, KeyValue, ModelBadge, Page, PageHeader, QueryView, Section, TimeAgo } from "../components/ui";

const WILL_SHOW: WillShow[] = [
  {
    title: "Volume and outcome rates",
    detail: "Decisions per hour and day, and approve, decline and refer rates by channel, product and risk band, next to the same hour last week.",
  },
  {
    title: "Service health",
    detail: "Latency percentiles, errors, time-outs, fallback use and knock-out rates, against the agreed service levels.",
  },
  {
    title: "Decision lookup",
    detail: "Find a decision by decision, application or loan id: inputs (masked by role), features, probability of default, policy path, reasons, versions, and the loan's later performance.",
  },
  {
    title: "Reason codes",
    detail: "How often each principal reason is given for declines, and the status of adverse-action notices.",
  },
  {
    title: "Policy in effect",
    detail: "The policy version that applied, with its version history and who approved each change.",
  },
];

function summarySentence(d: DecisionsData, s: StatusSummary | undefined): string {
  const live: unknown = d.live;
  if (!isUnavailable(live)) return "The decision API is reporting live data.";
  const who = s?.serving
    ? `${s.serving.label} holds the serving alias in the registry but decides nothing`
    : "the legacy policy score still decides every application";
  return `No application has been decided by a model yet: the real-time decision API is not deployed, so ${who}, and there are no volumes, approval rates or latencies to show.`;
}

export default function Decisions() {
  const q = useDecisions();
  const status = useStatus();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => (
          <>
            <PageHeader
              eyebrow="Now"
              title="Decisions"
              summary={summarySentence(d, status.data)}
              meta={
                status.data?.generated_at ? (
                  <span>
                    Status checked <TimeAgo iso={status.data.generated_at} />
                  </span>
                ) : undefined
              }
            />

            <LiveSection d={d} />

            <Section
              title="What a decision will look like"
              note="The response the endpoint will return for one application, annotated. Agents are never in this path: a decision comes from the approved model and approved policy only."
            >
              <ExampleDecision preview={d.preview} />
            </Section>

            <TodaySection status={status.data} />
          </>
        )}
      </QueryView>
    </Page>
  );
}

function LiveSection({ d }: { d: DecisionsData }) {
  const live: unknown = d.live;
  return (
    <Section title="Live decisions">
      {isUnavailable(live) ? (
        <NotBuiltPanel title="The decision API is not live" reason={live.reason} requires={live.requires} willShow={WILL_SHOW} />
      ) : (
        <EmptyState title="Live decision data arrived in a shape this console version cannot show yet" />
      )}
    </Section>
  );
}

function TodaySection({ status }: { status: StatusSummary | undefined }) {
  if (!status) return null;
  const waiting = status.decisions_waiting;
  return (
    <Section title="Who decides today" note="Until the decision API is deployed, no model can take application traffic.">
      <Card>
        <KeyValue
          items={[
            [
              "Making decisions",
              status.serving ? (
                <span className="row" style={{ gap: 6 }}>
                  <ModelBadge model={status.serving} />
                  {!status.api.live && <span className="small muted">holds the serving alias; the decision API is not deployed, so it decides nothing yet</span>}
                </span>
              ) : (
                <span>Legacy policy score. Nothing has been promoted.</span>
              ),
            ],
            [
              "Waiting for a person",
              waiting > 0 ? (
                <Link to="/approvals">
                  {waiting} promotion decision{waiting === 1 ? "" : "s"}
                </Link>
              ) : (
                <span>Nothing</span>
              ),
            ],
            ["Promotions and rollback", <Link key="r" to="/rollouts">Rollouts</Link>],
            ["Shadow scores", <Link key="s" to="/shadow">Shadow scoring</Link>],
          ]}
        />
      </Card>
    </Section>
  );
}
