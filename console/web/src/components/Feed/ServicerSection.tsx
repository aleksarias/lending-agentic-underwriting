/**
 * The live loan status feed for loans the decision API approved: every file read (accepted, quarantined, held),
 * why records were quarantined, corrections that restated earlier months, the book by status each month, and how many
 * loans have matured under the active definition. Aggregates and file-level records only.
 */
import type { ServicerFeed } from "../../api/types";
import { fmtDateTime, fmtNum, fmtUsd } from "../../lib/format";
import { BarSeriesChart, useChartColors } from "../charts";
import { Banner, Card, DataTable, EmptyState, Pill, Section, Tiles, TimeAgo } from "../ui";

export function servicerSentence(s: ServicerFeed): string {
  const last = s.files[0];
  if (!last) return "The loan status feed is connected but no file has been read yet.";
  const latestBook = s.book[s.book.length - 1];
  const book = latestBook ? ` ${fmtNum(latestBook.loans_reporting)} loans reported for ${latestBook.period_month}.` : "";
  const held = s.held.length ? ` ${s.held.length} file${s.held.length === 1 ? " is" : "s are"} held for review.` : "";
  return `The loan status feed is live: the newest file (${last.file_month}) was read ${fmtDateTime(last.ingested_at)} with ${fmtNum(last.accepted)} records accepted and ${fmtNum(last.quarantined)} quarantined.${book}${held}`;
}

export function ServicerSection({ s }: { s: ServicerFeed }) {
  const c = useChartColors();
  const matured = s.maturation[s.maturation.length - 1];
  return (
    <>
      {s.held.length > 0 && (
        <Banner tone="crit" title="Feed files held for review">
          Too many records in {s.held.join(", ")} failed the checks, so nothing from {s.held.length === 1 ? "it" : "them"} reached the loan history. Review the quarantine below,
          then release with <span className="mono">lau feed release &lt;file&gt;</span> (the bad records stay quarantined).
        </Banner>
      )}
      <Section title="Loan status feed" note="One file per month from the (simulated) servicer: bookings, a status record for every open loan, and corrections to earlier months.">
        <div className="stack">
          <Tiles
            tiles={[
              { key: "files", label: "Files read", value: fmtNum(s.files.length), sub: s.files[0] ? `newest ${s.files[0].file_month}` : undefined },
              { key: "quarantine", label: "Records quarantined", value: fmtNum(s.quarantine.total), sub: "failed a check; never dropped silently", tone: s.quarantine.total ? "warn" : "good" },
              { key: "restated", label: "Restatements", value: fmtNum(s.restatements.total), sub: "corrections that changed a known month" },
              {
                key: "matured",
                label: "Matured loans",
                value: matured ? fmtNum(matured.matured) : "—",
                sub: matured ? `of ${fmtNum(matured.booked)} booked, through ${matured.as_of_month}` : "none yet",
              },
            ]}
          />
          {s.book.length > 0 && (
            <Card>
              <BarSeriesChart
                title="Loans reporting each month, by status"
                data={s.book}
                xKey="period_month"
                stacked
                height={260}
                series={[
                  { key: "current", label: "Current", color: c.good },
                  { key: "dpd_30", label: "30 days past due", color: c.warn },
                  { key: "dpd_60", label: "60 days", color: c.accent },
                  { key: "dpd_90_plus", label: "90+ days", color: c.crit },
                  { key: "forbearance", label: "Forbearance", color: c.muted },
                  { key: "charged_off", label: "Charged off", color: c.ink },
                ]}
              />
            </Card>
          )}
        </div>
      </Section>

      <Section title="Files" note="Each file is read once. A file whose share of failing records exceeds the limit is held whole until a person releases it.">
        <Card flush>
          <DataTable
            rows={s.files}
            rowKey={(f) => `${f.feed_file}-${f.ingested_at}`}
            initialSort={{ key: "month", dir: "desc" }}
            maxHeight={320}
            columns={[
              { key: "month", header: "Month", render: (f) => f.file_month ?? "—", sort: (f) => f.file_month },
              { key: "status", header: "Status", render: (f) => <Pill tone={f.status === "held" ? "crit" : "good"}>{f.released_by ? `released by ${f.released_by}` : f.status}</Pill> },
              { key: "records", header: "Records", align: "right", render: (f) => fmtNum(f.records), sort: (f) => f.records },
              { key: "accepted", header: "Accepted", align: "right", render: (f) => fmtNum(f.accepted), sort: (f) => f.accepted },
              { key: "q", header: "Quarantined", align: "right", render: (f) => fmtNum(f.quarantined), sort: (f) => f.quarantined },
              { key: "r", header: "Restated", align: "right", render: (f) => fmtNum(f.restatements), sort: (f) => f.restatements },
              { key: "when", header: "Read", render: (f) => <TimeAgo iso={f.ingested_at} />, sort: (f) => f.ingested_at },
            ]}
          />
        </Card>
      </Section>

      <div className="grid cols-2">
        <Section title="Why records were quarantined">
          {s.quarantine.by_reason.length === 0 ? (
            <EmptyState title="Nothing quarantined" />
          ) : (
            <Card flush>
              <DataTable
                rows={s.quarantine.by_reason}
                rowKey={(r) => r.reason}
                initialSort={{ key: "n", dir: "desc" }}
                columns={[
                  { key: "reason", header: "Check that failed", render: (r) => r.reason },
                  { key: "n", header: "Records", align: "right", render: (r) => fmtNum(r.n), sort: (r) => r.n },
                ]}
              />
            </Card>
          )}
        </Section>
        <Section title="Recent restatements">
          {s.restatements.recent.length === 0 ? (
            <EmptyState title="No restatements yet" />
          ) : (
            <Card flush>
              <DataTable
                rows={s.restatements.recent}
                rowKey={(r) => `${r.loan_id}-${r.period_month}-${r.reported_month}`}
                columns={[
                  { key: "loan", header: "Loan", render: (r) => <span className="mono xs">{r.loan_id}</span> },
                  { key: "period", header: "Month", render: (r) => r.period_month },
                  { key: "dpd", header: "Days past due", render: (r) => `${r.dpd_before ?? "?"} → ${r.dpd_after ?? "?"}` },
                  { key: "when", header: "Corrected in", render: (r) => r.reported_month },
                ]}
              />
            </Card>
          )}
        </Section>
      </div>

      {s.book.length > 0 && (
        <Section title="Book balance">
          <Card>
            <BarSeriesChart title="Outstanding balance of loans reporting" data={s.book} xKey="period_month" series={[{ key: "balance_outstanding", label: "Balance", color: c.accent }]} yFormat={(v) => fmtUsd(v, 0)} height={200} />
          </Card>
        </Section>
      )}
    </>
  );
}
