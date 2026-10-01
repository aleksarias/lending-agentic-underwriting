/**
 * Cash-flow cohort explorer: quarterly aggregates of the bank-statement variables over every application that came
 * through the door (approved and declined). Only aggregates are shown; there are no applicant rows.
 */
import type { CashflowCohorts } from "../../api/types";
import { fmtNum, fmtPct, fmtPp, fmtUsd } from "../../lib/format";
import { LineSeriesChart } from "../charts";
import { WrapHeader as H } from "../Models/shared";
import { Card, DataTable, EmptyState, Section, TimeAgo, type Column } from "../ui";
import "./data.css";

type Cohort = CashflowCohorts["cohorts"][number];

interface Metric {
  key: "income_mean" | "nsf_rate" | "overdraft_share" | "housing_on_time_mean";
  title: string;
  label: string;
  fmt: (v: number) => string;
}

const METRICS: Metric[] = [
  { key: "income_mean", title: "Average monthly income", label: "Mean income", fmt: (v) => fmtUsd(v, 0) },
  { key: "nsf_rate", title: "Applicants with an NSF fee", label: "NSF incidence", fmt: (v) => fmtPct(v, 1) },
  { key: "overdraft_share", title: "Applicants with an overdraft", label: "Overdraft incidence", fmt: (v) => fmtPct(v, 1) },
  { key: "housing_on_time_mean", title: "Housing payments made on time", label: "Housing on time", fmt: (v) => fmtPct(v, 1) },
];

export function CashflowExplorer({ data }: { data: CashflowCohorts }) {
  const cohorts = data.cohorts;
  if (cohorts.length === 0) {
    return (
      <Section id="cashflow" title="Cash-flow cohorts">
        <EmptyState title="No cash-flow cohorts yet">
          The evidence job summarizes the bank-statement variables by origination quarter, and only when those columns exist in the applications data. Run <code>lau evidence run</code> after the
          cash-flow data is loaded; quarterly charts and the exact table then appear here.
        </EmptyState>
      </Section>
    );
  }
  const first = cohorts[0];
  const last = cohorts[cohorts.length - 1];
  const total = cohorts.reduce((s, c) => s + c.n, 0);
  const change = (a: number | null, b: number | null, kind: "pct" | "pp") =>
    a == null || b == null ? "—" : kind === "pct" ? `${b >= a ? "+" : "−"}${fmtNum(Math.abs((b / a - 1) * 100), 1)}%` : fmtPp(b - a, 1);

  const cols: Column<Cohort>[] = [
    { key: "cohort", header: <H width="5.5rem">Origination quarter</H>, render: (c) => c.cohort, sort: (c) => c.cohort },
    { key: "n", header: <H width="6rem">Applications</H>, align: "right", render: (c) => fmtNum(c.n), sort: (c) => c.n },
    { key: "income", header: <H width="5rem">Mean income</H>, align: "right", render: (c) => fmtUsd(c.income_mean, 0), sort: (c) => c.income_mean },
    { key: "cv", header: <H width="5.5rem">Income volatility, median</H>, align: "right", render: (c) => fmtPct(c.income_cv_median, 1), sort: (c) => c.income_cv_median },
    { key: "eti", header: <H width="5.5rem">Outflows to inflows, median</H>, align: "right", render: (c) => fmtPct(c.expense_to_income_median, 1), sort: (c) => c.expense_to_income_median },
    { key: "bal", header: <H width="5.5rem">Minimum balance, median</H>, align: "right", render: (c) => fmtUsd(c.min_balance_median, 0), sort: (c) => c.min_balance_median },
    { key: "nsf", header: <H width="4.5rem">NSF incidence</H>, align: "right", render: (c) => fmtPct(c.nsf_rate, 1), sort: (c) => c.nsf_rate },
    { key: "od", header: <H width="5rem">Overdraft incidence</H>, align: "right", render: (c) => fmtPct(c.overdraft_share, 1), sort: (c) => c.overdraft_share },
    { key: "house", header: <H width="5rem">Housing on time</H>, align: "right", render: (c) => fmtPct(c.housing_on_time_mean, 1), sort: (c) => c.housing_on_time_mean },
  ];

  return (
    <Section
      id="cashflow"
      title="Cash-flow cohorts"
      note={
        <>
          Quarterly aggregates of the bank-statement (cash-flow) variables, six months of history per application, over every application that came through the door, approved or
          declined. {fmtNum(cohorts.length)} cohorts, {first.cohort} to {last.cohort}, {fmtNum(total)} applications.
          {data.computed_at && (
            <>
              {" "}
              Computed <TimeAgo iso={data.computed_at} />.
            </>
          )}{" "}
          These are aggregates: no applicant rows are shown.
        </>
      }
    >
      <div className="small">
        {last.cohort} against {first.cohort}: mean income {change(first.income_mean, last.income_mean, "pct")}, NSF incidence {change(first.nsf_rate, last.nsf_rate, "pp")}, overdraft incidence{" "}
        {change(first.overdraft_share, last.overdraft_share, "pp")}, housing paid on time {change(first.housing_on_time_mean, last.housing_on_time_mean, "pp")}.
      </div>
      <div className="data-charts">
        {METRICS.map((m) => {
          const vals = cohorts.map((c) => c[m.key]).filter((v): v is number => v != null);
          return (
            <Card key={m.key} title={m.title} kind="measured">
              <LineSeriesChart
                title={`${m.title} by origination quarter`}
                data={cohorts.map((c) => ({ cohort: c.cohort, value: c[m.key] }))}
                xKey="cohort"
                series={[{ key: "value", label: m.label, color: 0, width: 2.5 }]}
                yFormat={m.fmt}
                height={200}
              />
              {vals.length > 0 && (
                <div className="data-axis-note">
                  Lowest {m.fmt(Math.min(...vals))}, highest {m.fmt(Math.max(...vals))}. The vertical axis does not start at zero.
                </div>
              )}
            </Card>
          );
        })}
      </div>
      <Card flush kind="measured">
        <DataTable rows={cohorts} columns={cols} rowKey={(c) => c.cohort} initialSort={{ key: "cohort", dir: "asc" }} />
      </Card>
      <div className="xs muted">
        NSF and overdraft incidence are the share of applications with at least one such event in the six months; income volatility is the median coefficient of variation of monthly income;
        outflows to inflows and minimum balance are medians across applications.
      </div>
    </Section>
  );
}
