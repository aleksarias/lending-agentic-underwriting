/**
 * Screen 11 — Loan status feed: how does loan performance reach the system?
 *
 * There is no live servicing feed yet. Performance arrives as batch data versions, so this screen leads with the
 * latest version, then shows what the data already says without any definition of default (vintage curves), how many
 * loans mature under each definition, and what a live feed would need.
 */
import { useFeed, useStatus } from "../api/hooks";
import type { FeedData } from "../api/types";
import { MaturationSection } from "../components/Feed/MaturationSection";
import { ServicerSection, servicerSentence } from "../components/Feed/ServicerSection";
import { VintageSection } from "../components/Feed/VintageSection";
import { NotBuiltPanel, type WillShow } from "../components/Operate/NotBuiltPanel";
import { Banner, Page, PageHeader, QueryView, Section, Tiles, TimeAgo } from "../components/ui";
import { fmtAgo, fmtDateTime, fmtNum, shortVersion } from "../lib/format";

const WILL_SHOW: WillShow[] = [
  { title: "Freshness and volume", detail: "When each status file arrived, how many records it held, and whether it was on schedule." },
  { title: "Quality checks", detail: "Every loan linked to a decision, days past due moving at most one bucket a month unless cured, closed loans staying closed, no negative balances. Failing records are quarantined and raise an alert, never silently dropped." },
  { title: "Restatements", detail: "Corrections the servicer makes to earlier months, by period, so labels can be rebuilt as known on any date." },
  { title: "Status transitions", detail: "Current to 30 to 60 days past due, cures, charge-offs and payoffs this period against last." },
  { title: "Unlinked loans", detail: "Loans with no matching decision, and decisions with no booking after the expected period." },
];

function summarySentence(f: FeedData): string {
  if (f.servicer) return servicerSentence(f.servicer);
  const p = f.performance;
  const state = f.live ? "The loan status feed is live" : "The loan status feed is not live";
  if (!p.data_version) return `${state} and no performance data has been loaded yet.`;
  const through = p.as_of_month ? `runs through ${p.as_of_month}` : "has no stated end month";
  const size = p.n_applications != null ? ` and covers ${fmtNum(p.n_applications)} applications` : "";
  const when = p.loaded_at ? `, loaded ${fmtAgo(p.loaded_at)}` : "";
  return `${state}: performance arrives as batch data versions. The latest, ${shortVersion(p.data_version)}, ${through}${size}${when}.`;
}

export default function Feed() {
  const q = useFeed();
  const status = useStatus();
  return (
    <Page>
      <QueryView query={q} loadingHeight={360}>
        {(f) => (
          <>
            <PageHeader
              eyebrow="Data and feedback"
              title="Loan status feed"
              summary={summarySentence(f)}
              meta={
                f.vintage.computed_at ? (
                  <span>
                    Vintage curves computed <TimeAgo iso={f.vintage.computed_at} /> by the evidence job
                  </span>
                ) : undefined
              }
            />

            {f.servicer ? (
              <ServicerSection s={f.servicer} />
            ) : (
              <Banner tone="neutral" title="Not a live feed">
                {f.reason}
              </Banner>
            )}

            <Section title="Historical performance data" note="The batch version that the historical labels, evaluations and vintage curves were built from.">
              <Tiles
                tiles={[
                  { key: "version", label: "Data version", value: shortVersion(f.performance.data_version), sub: f.performance.data_version ? "latest batch load" : "none loaded" },
                  { key: "through", label: "Performance through", value: f.performance.as_of_month ?? "—", sub: "last month of loan status in the data" },
                  { key: "loaded", label: "Loaded", value: fmtAgo(f.performance.loaded_at), sub: fmtDateTime(f.performance.loaded_at) },
                  { key: "apps", label: "Applications", value: fmtNum(f.performance.n_applications), sub: "in this data version" },
                ]}
              />
            </Section>

            <VintageSection vintage={f.vintage} />
            <MaturationSection rows={f.maturation} activeVersion={status.data?.active_definition?.version} />

            {!f.live && (
              <Section title="What a live feed needs">
                <NotBuiltPanel
                  title="The servicing feed is not connected"
                  reason="Until a feed is connected, performance reaches the system as whole batch data versions, so nothing on this screen changes between loads. A live feed adds freshness, quality results and restatements, and vintage curves that update as loans age."
                  requires={f.requires}
                  willShow={WILL_SHOW}
                />
              </Section>
            )}
          </>
        )}
      </QueryView>
    </Page>
  );
}
