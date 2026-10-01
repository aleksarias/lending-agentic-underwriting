/**
 * Screen 14 (detail) — one agent report. The text is an agent's claim, so it sits in a "proposed" card; the page says
 * so and links to the measured evidence (harness evaluations, the candidate's evidence packet, the cycle).
 */
import { Link, useParams } from "react-router-dom";
import { useReport, useReports } from "../api/hooks";
import type { Report } from "../api/types";
import { DefBadge, VerdictPill, kindLabel, roleLabel } from "../components/Agents/shared";
import { Markdown } from "../components/Markdown";
import { Card, EmptyState, ErrorState, KeyValue, KindTag, Loading, Page, PageHeader, Pill, Section, TimeAgo, links } from "../components/ui";
import { fmtAgo, fmtDateTime, refLabel } from "../lib/format";

/** Evaluation ids the report cites, in order of first mention. */
function citedEvaluations(body: string): string[] {
  return [...new Set(body.match(/\bev-[0-9a-f]{8,12}\b/g) ?? [])];
}

function sentence(r: Report): string {
  const who = `The ${roleLabel(r.author).toLowerCase()} agent wrote this ${kindLabel(r.kind).toLowerCase()}`;
  const about = r.candidate_ref ? ` on candidate ${refLabel(r.candidate_ref)}` : "";
  const where = r.cycle_id ? `, in cycle ${r.cycle_id}` : "";
  const verdict = r.verdict ? `; its verdict is ${r.verdict}, which is an opinion, not a measurement` : "; it is an agent's claim, not a measurement";
  return `${who}${about} ${fmtAgo(r.created_at)}${where}${verdict}.`;
}

function OtherReports({ report }: { report: Report }) {
  const q = useReports({ cycle_id: report.cycle_id });
  const others = (q.data ?? []).filter((r) => r.report_id !== report.report_id);
  if (!report.cycle_id || !others.length) return null;
  return (
    <Section title="Other reports from the same cycle">
      <Card flush kind="proposed">
        <ul className="list" style={{ padding: "0 14px" }}>
          {others.map((r) => (
            <li key={r.report_id} className="item row between">
              <span className="row" style={{ gap: 8 }}>
                <Link to={links.report(r.report_id)}>{r.title || r.report_id}</Link>
                <span className="xs muted">{roleLabel(r.author)}</span>
              </span>
              <VerdictPill verdict={r.verdict} />
            </li>
          ))}
        </ul>
      </Card>
    </Section>
  );
}

function NotFound({ id }: { id: string | undefined }) {
  return (
    <Page>
      <PageHeader eyebrow="Agents" title="Report not found" summary={id ? `There is no report with the id ${id}.` : "No report id was given."} />
      <EmptyState title="This report does not exist">
        It may have been mistyped, or the link may come from another environment. <Link to="/agents">Open the reports library</Link>.
      </EmptyState>
    </Page>
  );
}

export default function ReportDetail() {
  const { reportId } = useParams<{ reportId: string }>();
  const q = useReport(reportId);
  if (q.isError) {
    const status = (q.error as { status?: number } | null)?.status;
    if (status === 404 || status === 400) return <NotFound id={reportId} />;
    return (
      <Page>
        <ErrorState error={q.error} />
      </Page>
    );
  }
  // pending without data covers loading and a retry that is waiting for the tab to be visible
  if (!q.data) {
    return (
      <Page>
        <Loading height={320} />
      </Page>
    );
  }
  const r = q.data;
  const evals = citedEvaluations(r.body);
  return (
    <Page>
      <PageHeader
        eyebrow="Agents"
        title={r.title || r.report_id}
        summary={sentence(r)}
        meta={
          <>
            <Link to="/agents">All reports</Link>
            <span>· definition of default</span>
            <DefBadge version={r.definition_version} />
          </>
        }
      />

      <div className="grid split">
        <Card title="About this report">
          <KeyValue
            items={[
              ["Author", roleLabel(r.author)],
              [
                "Kind",
                <span key="k">
                  {kindLabel(r.kind)} <span className="muted mono">({r.kind})</span>
                </span>,
              ],
              [
                "Verdict",
                <span key="v" className="row" style={{ gap: 6 }}>
                  <VerdictPill verdict={r.verdict} />
                  {r.verdict && <KindTag kind="proposed" />}
                </span>,
              ],
              ["Cycle", r.cycle_id ? <Link key="c" className="mono" to={links.cycle(r.cycle_id)}>{r.cycle_id}</Link> : "—"],
              [
                "Candidate",
                r.candidate_ref ? (
                  <Link key="cand" to={links.approval(r.candidate_ref)}>
                    {refLabel(r.candidate_ref)} <span className="muted mono">({r.candidate_ref})</span>
                  </Link>
                ) : (
                  <span className="muted">none: the report is about the cycle, not one model</span>
                ),
              ],
              ["Definition of default", <DefBadge key="d" version={r.definition_version} />],
              [
                "Written",
                <span key="w" title={fmtDateTime(r.created_at)}>
                  {fmtDateTime(r.created_at)} <span className="muted">(<TimeAgo iso={r.created_at} />)</span>
                </span>,
              ],
              ["Report id", <span key="id" className="mono">{r.report_id}</span>],
            ]}
          />
        </Card>

        <Card title="Where the measured evidence is">
          <p className="small" style={{ margin: "0 0 8px" }}>
            The text below is an agent's claim. Its numbers were read from tools the agent called, and an agent can misquote them: check them against these harness records.
          </p>
          <ul className="plain small">
            {r.candidate_ref && (
              <li>
                <Link to={links.approval(r.candidate_ref)}>Evidence packet for {refLabel(r.candidate_ref)}</Link>: checks, benchmark position, holdout gate
              </li>
            )}
            {evals.map((id) => (
              <li key={id}>
                <Link className="mono" to={links.evaluation(id)}>
                  {id}
                </Link>{" "}
                <span className="muted">harness evaluation cited in the text</span>
              </li>
            ))}
            {r.cycle_id && (
              <li>
                <Link to={links.cycle(r.cycle_id)}>Cycle {r.cycle_id}</Link>: plan, agent runs, trace and cost
              </li>
            )}
            {!r.candidate_ref && !evals.length && !r.cycle_id && <li className="muted">This report links to no measured record.</li>}
          </ul>
        </Card>
      </div>

      <Section title="Report text">
        <Card kind="proposed">
          <div className="row between" style={{ marginBottom: 8 }}>
            <span className="small muted">Written by the {roleLabel(r.author).toLowerCase()} agent</span>
            <span className="row" style={{ gap: 6 }}>
              <Pill tone="neutral">agent claim</Pill>
              <KindTag kind="proposed" />
            </span>
          </div>
          {r.body.trim() ? <Markdown source={r.body} /> : <EmptyState title="This report has no text" />}
        </Card>
      </Section>

      <OtherReports report={r} />
    </Page>
  );
}
