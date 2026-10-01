/**
 * Screen 18 — Alerts and service levels: what has drifted, and has a person looked?
 *
 * Open alerts come first (raised by the newest monitoring run and not acknowledged), then the monitoring runs behind
 * them, then the history. A high alert queues an improvement cycle; acknowledging records who saw it and why, and
 * changes nothing else. Service-level and notification sources that are not built yet say what they wait for.
 */
import { Link } from "react-router-dom";
import { useAlerts, useSettings, useStatus } from "../api/hooks";
import type { AlertItem, AlertsData } from "../api/types";
import { AlertHistory } from "../components/Alerts/HistoryTable";
import { alertBrief, classify } from "../components/Alerts/logic";
import { OpenAlerts } from "../components/Alerts/OpenAlerts";
import { RunsTable } from "../components/Alerts/RunsTable";
import { ServiceLevels } from "../components/Alerts/ServiceLevels";
import { Updated } from "../components/Operate/Updated";
import { useThresholds } from "../components/Operate/thresholds";
import { EmptyState, Page, PageHeader, QueryView, Section, TimeAgo } from "../components/ui";
import { fmtAgo, fmtAuc } from "../lib/format";

function summarySentence(data: AlertsData, open: AlertItem[]): string {
  if (!data.available) return "Monitoring has not run yet, so there are no alerts to review.";
  if (open.length === 0) {
    const run = data.monitoring_runs[0];
    return run ? `No alerts are open: the latest monitoring run, ${fmtAgo(run.ts)}, raised ${run.alerts === 0 ? "none" : `${run.alerts}, all acknowledged`}.` : "No alerts are open.";
  }
  const count = (s: AlertItem["severity"]) => open.filter((a) => a.severity === s).length;
  const severities = (["high", "medium", "low"] as const)
    .filter((s) => count(s) > 0)
    .map((s) => `${count(s)} ${s}`)
    .join(" and ");
  const shown = open.slice(0, 3).map(alertBrief);
  const more = open.length > shown.length ? ` and ${open.length - shown.length} more` : "";
  const cycle = count("high") > 0 ? "; a high alert queues an improvement cycle" : "";
  return `${severities} alert${open.length === 1 ? " is" : "s are"} open from the latest checks (${shown.join(", ")}${more})${cycle}.`;
}

export default function Alerts() {
  const q = useAlerts();
  const status = useStatus();
  const settings = useSettings();
  const th = useThresholds();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(data) => {
          const { open, history } = classify(data);
          const latest = data.monitoring_runs[0];
          return (
            <>
              <PageHeader
                eyebrow="Decide and operate"
                title="Alerts and service levels"
                summary={summarySentence(data, open)}
                meta={
                  <>
                    <Updated at={q.dataUpdatedAt} />
                    {latest && (
                      <span>
                        · latest monitoring run <TimeAgo iso={latest.ts} />
                      </span>
                    )}
                  </>
                }
              />

              {!data.available ? (
                <Section title="Open alerts">
                  <EmptyState title="Monitoring has not run yet">
                    {data.reason ?? "No monitoring run is recorded."} After a run, alerts appear here when the score or a feature has drifted from the baseline, or when realized
                    defaults differ from what the model expected.
                  </EmptyState>
                </Section>
              ) : (
                <>
                  <Section
                    title="Open alerts"
                    note={
                      <>
                        Raised by the latest run of the check that raises it (monitoring, the loan feed, the maturation check) and not yet acknowledged. PSI (population stability index) measures how far a distribution has moved from the baseline
                        built for the definition of default
                        {th.psiWarn != null && th.psiAlert != null
                          ? `: below ${fmtAuc(th.psiWarn, 2)} is stable, from ${fmtAuc(th.psiWarn, 2)} a warning (medium), from ${fmtAuc(th.psiAlert, 2)} an alert (high)`
                          : ""}
                        . A high alert queues an improvement cycle, which you can follow on <Link to="/upcoming">Upcoming</Link>.
                      </>
                    }
                  >
                    <OpenAlerts alerts={open} th={th} actionsEnabled={status.data?.actions_enabled} user={status.data?.user ?? null} />
                  </Section>

                  <Section title="Monitoring runs" note="The measurements behind the alerts. Each run compares the newest applications with the definition's monitoring baseline.">
                    <RunsTable runs={data.monitoring_runs} alerts={data.alerts} th={th} />
                  </Section>

                  <Section title="Alert history" note="Acknowledged alerts, and alerts from earlier monitoring runs.">
                    <AlertHistory alerts={history} th={th} />
                  </Section>
                </>
              )}

              <Section title="Service levels and notifications" note="Alert sources beyond model monitoring. Each one begins when what it watches exists.">
                <ServiceLevels status={status.data} notifications={settings.data?.notifications} />
              </Section>
            </>
          );
        }}
      </QueryView>
    </Page>
  );
}
