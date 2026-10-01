/**
 * Screen 1 — Overview. Answers: what is the system doing, is it getting better, and what needs a person?
 * Reference implementation: other screens follow this anatomy (header sentence → answer → detail → raw evidence).
 */
import { Link } from "react-router-dom";
import { useOverview, useStatus } from "../api/hooks";
import { EventList, StageList, WaitingList } from "../components/lists";
import { Card, DefinitionBadge, Page, PageHeader, QueryView, Section, Tiles, TimeAgo } from "../components/ui";

export default function Overview() {
  const overview = useOverview();
  const status = useStatus();
  return (
    <Page>
      <QueryView query={overview} loadingHeight={320}>
        {(o) => {
          const stale = o.pipeline.filter((s) => s.status !== "fresh").length;
          return (
            <>
              <PageHeader
                eyebrow="Now"
                title="Overview"
                summary={o.status_sentence}
                meta={
                  <>
                    <span>Definition of default</span>
                    <DefinitionBadge def={status.data?.active_definition} />
                    {status.data?.generated_at && (
                      <span>
                        · updated <TimeAgo iso={status.data.generated_at} />
                      </span>
                    )}
                  </>
                }
              />

              <Tiles tiles={o.tiles} />

              <div className="grid split">
                <Section
                  title="Waiting for a person"
                  right={
                    <Link className="small" to="/approvals">
                      All approvals
                    </Link>
                  }
                >
                  <Card>
                    <WaitingList items={o.waiting} />
                  </Card>
                </Section>
                <Section
                  title="Pipeline for the active definition"
                  right={<span className="small muted">{stale ? `${stale} of ${o.pipeline.length} stages not fresh` : "all stages fresh"}</span>}
                >
                  <Card>
                    <StageList stages={o.pipeline} />
                  </Card>
                </Section>
              </div>

              <Section
                title="Recent events"
                note="Measured events come from the harness and monitoring; agent reports are claims until the harness checks them."
                right={
                  <Link className="small" to="/history">
                    Full history
                  </Link>
                }
              >
                <Card>
                  <EventList events={o.recent_events} />
                </Card>
              </Section>
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
