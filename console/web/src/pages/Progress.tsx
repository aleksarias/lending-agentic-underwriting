/**
 * Screen 4 — Progress: is the system improving?
 *
 * Every number here is a harness measurement. The verdict and guardrails come from the improvement ledger; the
 * matrix and differences from the benchmark ledger, where every model (including ones trained under other
 * definitions) is re-scored on the same loans under the same frozen benchmark definitions. That is the only place
 * models from different definitions may share an axis.
 */
import { useSearchParams } from "react-router-dom";
import { useProgress } from "../api/hooks";
import type { BenchmarkDef, BenchmarkMatrix, BenchmarkRow, DiffRow, GuardrailRow, ProgressData, Verdict } from "../api/types";
import { isUnavailable } from "../api/types";
import { ProductionEvidenceView } from "../components/Production/ProductionEvidence";
import { IntervalChart, LineSeriesChart, Sparkline } from "../components/charts";
import {
  Banner,
  Card,
  DataTable,
  EmptyState,
  KeyValue,
  ModelBadge,
  Page,
  PageHeader,
  Pill,
  QueryView,
  Section,
  Tabs,
  Tiles,
  TimeAgo,
  UnavailableState,
  links,
  type Column,
} from "../components/ui";
import { fmtAuc, fmtDate, fmtDiff, fmtInterval, fmtNum, fmtPct, fmtUsd, refLabel, shortVersion, verdictLabel, verdictTone } from "../lib/format";
import { Link } from "react-router-dom";

export default function Progress() {
  const [params, setParams] = useSearchParams();
  const asOf = params.get("as_of");
  const q = useProgress(asOf);
  const setAsOf = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("as_of", v);
    else next.delete("as_of");
    setParams(next, { replace: true });
  };
  return (
    <Page>
      <QueryView query={q} loadingHeight={360}>
        {(p) => (
          <>
            <PageHeader
              eyebrow="Over time"
              title="Is the system improving?"
              summary={summarySentence(p)}
              actions={
                <label className="row small" style={{ gap: 6 }}>
                  <span className="muted">Evidence as of</span>
                  <input type="date" value={asOf ?? ""} onChange={(e) => setAsOf(e.target.value)} aria-label="Show the evidence as computed at the end of this day" />
                  {asOf && (
                    <button type="button" className="btn small" onClick={() => setAsOf("")}>
                      Now
                    </button>
                  )}
                </label>
              }
              meta={
                p.verdict?.computed_at ? (
                  <span>
                    Evidence computed <TimeAgo iso={p.verdict.computed_at} /> by the harness (no agent input)
                  </span>
                ) : undefined
              }
            />
            {p.as_of && (
              <Banner tone="neutral" title={`Time travel: the evidence as it stood at the end of ${asOf}`}>
                Every number below comes from the newest evidence run computed by then; later runs are ignored. Choose Now to return to the latest evidence.
              </Banner>
            )}
            {!p.as_of && p.verdict?.stale_reason && (
              <Banner tone="warn" title="This evidence may be out of date">
                {p.verdict.stale_reason}
              </Banner>
            )}
            <VerdictBanner verdict={p.verdict} matrix={p.benchmark} />
            <LedgerSection matrix={p.benchmark} />
            <DifferencesSection p={p} />
            <LineageSection p={p} />
            <GuardrailsSection rows={p.guardrails} />
            <ProcessSection p={p} />
            <DenominatorSection p={p} />
            <Section title="Production evidence" note="Predicted against realized default rates for the loans each champion actually decided.">
              {isUnavailable(p.production) ? (
                <UnavailableState u={p.production} title="No production evidence yet" />
              ) : (
                <ProductionEvidenceView p={p.production} />
              )}
            </Section>
          </>
        )}
      </QueryView>
    </Page>
  );
}

function summarySentence(p: ProgressData): string {
  if (!p.verdict) return "No evidence has been computed yet. Run the evidence job to benchmark every model on the same loans.";
  const n = p.benchmark?.rows.filter((r) => r.model.kind !== "reference").length ?? 0;
  const tried = p.denominator ? ` ${p.denominator.tests_total} validation tests were run under the active definition.` : "";
  return `${p.verdict.title}. ${n} model${n === 1 ? "" : "s"} re-scored on the same loans.${tried}`;
}

// ------------------------------------------------------------------------------------------------ verdict
function VerdictBanner({ verdict, matrix }: { verdict: Verdict | null; matrix: BenchmarkMatrix | null }) {
  if (!verdict) {
    return (
      <EmptyState title="No verdict yet">
        The verdict appears after the evidence job runs (<code>lau evidence run</code>). It re-scores every model on the newest matured loans
        and applies the rules in the design: improved, no detectable change, not the best available, regressed, or not enough evidence.
      </EmptyState>
    );
  }
  const primary = matrix?.definitions.find((d) => d.key === verdict.primary_benchmark);
  return (
    <Banner tone={verdictTone(verdict.code)} title={`${verdictLabel(verdict.code)}: ${verdict.title}`}>
      <p style={{ margin: "4px 0 10px" }}>{verdict.detail}</p>
      <KeyValue
        items={[
          ["Primary benchmark", primary ? <BenchBadge def={primary} /> : verdict.primary_benchmark],
          ["Best known model", <ModelBadge model={verdict.best_known} />],
          ["Newest challenger", <ModelBadge model={verdict.newest_challenger} />],
          ["Making decisions", verdict.serving ? <ModelBadge model={verdict.serving} /> : <span>Legacy policy score (nothing promoted yet)</span>],
          [
            "Lift over the frozen legacy score",
            verdict.lift_vs_reference ? (
              <span className="num">{fmtInterval(verdict.lift_vs_reference, 3)} AUC</span>
            ) : (
              <span className="muted">not measured</span>
            ),
          ],
        ]}
      />
    </Banner>
  );
}

function BenchBadge({ def }: { def: BenchmarkDef }) {
  return (
    <span className="badge" title={`Frozen benchmark definition ${def.version}`}>
      <span className="mono">{shortVersion(def.version)}</span>
      <span>{def.label}</span>
    </span>
  );
}

// ------------------------------------------------------------------------------------------ benchmark ledger
function LedgerSection({ matrix }: { matrix: BenchmarkMatrix | null }) {
  if (!matrix) {
    return (
      <Section title="Benchmark ledger">
        <EmptyState title="Not computed yet">Run the evidence job to score every model on the same loans.</EmptyState>
      </Section>
    );
  }
  const optimistic = matrix.rows.some((r) => r.selected_on_window);
  const columns: Column<BenchmarkRow>[] = [
    {
      key: "model",
      header: "Model",
      render: (r) => (
        <span className="row" style={{ gap: 6 }}>
          <ModelBadge model={r.model} />
          {r.model.kind !== "reference" && r.model.kind !== "unknown" && <span className="xs muted">{r.model.kind}</span>}
          {r.selected_on_window && (
            <span className="xs muted" title="Evaluated on this window during model selection: its score here is optimistic">
              †
            </span>
          )}
        </span>
      ),
      sort: (r) => r.model.label,
    },
    { key: "trained", header: "Trained under", render: (r) => <span className="small">{r.trained_under}</span> },
    ...matrix.definitions.map<Column<BenchmarkRow>>((d) => ({
      key: d.key,
      header: (
        <span title={`${d.label}: ${fmtNum(d.n_defaults)} defaults in the window`}>
          AUC {d.dpd} DPD{d.key === matrix.primary_definition ? " (primary)" : ""}
        </span>
      ),
      align: "right",
      render: (r) => {
        const cell = r.metrics[d.key];
        if (!cell) return "—";
        return (
          <span className="num">
            {fmtAuc(cell.auc, 4)}
            {r.is_best[d.key] && <span className="xs"> best</span>}
            {cell.ci_lo != null && cell.ci_hi != null && (
              <span className="ci">
                {fmtAuc(cell.ci_lo, 3)} to {fmtAuc(cell.ci_hi, 3)}
              </span>
            )}
          </span>
        );
      },
      className: (r) => (r.is_best[d.key] ? "cell-best" : undefined),
      sort: (r) => r.metrics[d.key]?.auc ?? null,
    })),
    {
      key: "bad",
      header: `Bad rate at ${fmtPct(matrix.fixed_approval_rate, 0)} approval`,
      align: "right",
      render: (r) => <span className="num">{fmtPct(r.bad_rate_at_fixed_approval, 1)}</span>,
      sort: (r) => (r.bad_rate_at_fixed_approval == null ? null : -r.bad_rate_at_fixed_approval),
    },
  ];
  return (
    <Section
      title="Benchmark ledger: every model on the same loans"
      note={
        <>
          {matrix.window.start} to {matrix.window.end} originations, {fmtNum(matrix.window.n_loans)} loans, scored under each frozen benchmark
          definition ({matrix.window.policy === "validation" ? "validation window" : "latest matured loans outside every holdout"}). Best in each
          column is outlined. Computed <TimeAgo iso={matrix.computed_at} />.
        </>
      }
    >
      <Card flush>
        <DataTable
          rows={matrix.rows}
          columns={columns}
          rowKey={(r) => r.model.key}
          initialSort={{ key: matrix.primary_definition, dir: "desc" }}
        />
      </Card>
      <div className="xs muted">
        Lower bad rate is better: the share of approved loans that default when each model approves the same {fmtPct(matrix.fixed_approval_rate, 0)} of
        applicants.
        {optimistic && " † Evaluated on this window while being selected, so its score here is optimistic."}
      </div>
    </Section>
  );
}

// ------------------------------------------------------------------------------------------------ differences
function DifferencesSection({ p }: { p: ProgressData }) {
  const [params, setParams] = useSearchParams();
  const defs = p.benchmark?.definitions ?? [];
  if (!defs.length) return null;
  const primary = p.benchmark!.primary_definition;
  const bench = params.get("bench") && defs.some((d) => d.key === params.get("bench")) ? params.get("bench")! : primary;
  const setBench = (k: string) => {
    const next = new URLSearchParams(params);
    if (k === primary) next.delete("bench");
    else next.set("bench", k);
    setParams(next, { replace: true });
  };
  const rows = (diffs: DiffRow[], withVersus: boolean) =>
    diffs
      .filter((d) => d.definition_key === bench && d.model.kind !== "reference")
      .sort((a, b) => b.diff.estimate - a.diff.estimate)
      .map((d) => ({ label: withVersus ? `${d.model.label} − ${d.versus.label}` : d.model.label, ...d.diff }));
  const ref = rows(p.reference_diffs, false);
  const best = rows(p.best_known_diffs, true);
  return (
    <Section
      title="Paired differences with 95% intervals"
      note="Each model minus the comparison on exactly the same loans (paired bootstrap). Green: the whole interval is above zero. Amber: the interval includes zero, so no difference is established. Red: entirely below zero."
      right={<Tabs tabs={defs.map((d) => ({ key: d.key, label: `${d.dpd} DPD` }))} value={bench} onChange={setBench} />}
    >
      <div className="stack" style={{ gap: "var(--gap)" }}>
        <Card title="Lift over the frozen legacy score (AUC): each model minus the legacy score" kind="measured">
          {ref.length ? <IntervalChart title="AUC difference from the legacy score" rows={ref} format={(v) => fmtDiff(v, 3)} zeroLabel="no lift" /> : <EmptyState title="No differences computed" />}
        </Card>
        <Card title="Difference from the best known model (AUC): the best is compared with the runner-up" kind="measured">
          {best.length ? (
            <IntervalChart title="AUC difference from the best known model" rows={best} format={(v) => fmtDiff(v, 3)} zeroLabel="same as best" />
          ) : (
            <EmptyState title="No differences computed" />
          )}
        </Card>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------------------- lineage
function LineageSection({ p }: { p: ProgressData }) {
  const pts = p.lineage;
  return (
    <Section title="Best known model over time" note="Lift of the best known model over the frozen legacy score, one point per day the evidence job ran.">
      {pts.length === 0 ? (
        <EmptyState title="No history yet">Each evidence run adds a point.</EmptyState>
      ) : pts.length === 1 ? (
        <Card kind="measured">
          <KeyValue
            items={[
              ["Date", fmtDate(pts[0].period)],
              ["Best known model", <ModelBadge model={pts[0].model} />],
              ["Lift over legacy", <span className="num">{fmtInterval(pts[0].lift_vs_reference, 3)} AUC</span>],
            ]}
          />
          <div className="xs muted" style={{ marginTop: 8 }}>
            One evidence run so far. The trend line appears once the evidence job has run on a second day.
          </div>
        </Card>
      ) : (
        <Card kind="measured">
          <LineSeriesChart
            title="AUC lift of the best known model over the legacy score, with 95% interval"
            data={pts.map((x) => ({ period: x.period, estimate: x.lift_vs_reference.estimate, lo: x.lift_vs_reference.lo, hi: x.lift_vs_reference.hi }))}
            xKey="period"
            series={[
              { key: "estimate", label: "Lift (AUC)", color: 0, width: 2.5 },
              { key: "lo", label: "95% lower", color: 0, dashed: true, width: 1 },
              { key: "hi", label: "95% upper", color: 0, dashed: true, width: 1 },
            ]}
            yFormat={(v) => fmtDiff(v, 3)}
            refLines={[{ y: 0, label: "legacy score", tone: "neutral" }]}
          />
          <div className="xs muted">
            {pts
              .filter((x) => x.event)
              .map((x) => `${fmtDate(x.period)}: ${x.event === "definition_change" ? "definition changed" : x.event}`)
              .join(" · ") || "No promotions or definition changes in this period."}
          </div>
        </Card>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------------------------------------- guardrails
const GUARD_TONE = { ok: "good", watch: "warn", breach: "crit", unknown: "neutral" } as const;

function guardFormat(key: string, v: number | null): string {
  if (v == null) return "—";
  if (key === "reason_code_coverage") return fmtPct(v, 1);
  if (key === "min_air") return fmtAuc(v, 2);
  return fmtAuc(v, 3);
}

function GuardrailsSection({ rows }: { rows: GuardrailRow[] }) {
  return (
    <Section title="Guardrails" note="Limits a better model must not break. Values are for the model the verdict rests on; the line shows earlier evaluations under the same definition.">
      {rows.length === 0 ? (
        <EmptyState title="No guardrails measured yet" />
      ) : (
        <div className="grid cols-3">
          {rows.map((g) => (
            <Card key={g.key} kind="measured">
              <div className="row between">
                <strong className="small">{g.label}</strong>
                <Pill tone={GUARD_TONE[g.status]}>{g.status}</Pill>
              </div>
              <div className="row between" style={{ marginTop: 6 }}>
                <span className="num" style={{ fontSize: 22, fontWeight: 700 }}>
                  {guardFormat(g.key, g.value)}
                </span>
                <Sparkline values={[...g.history.map((h) => h.value), ...(g.value != null ? [g.value] : [])]} tone={g.status === "breach" ? "crit" : g.status === "watch" ? "warn" : "accent"} />
              </div>
              <div className="xs muted">
                limit {g.direction === "max" ? "at most" : "at least"} {guardFormat(g.key, g.threshold)}
                {g.history.length ? ` · ${g.history.length} earlier evaluation${g.history.length === 1 ? "" : "s"}` : ""}
              </div>
            </Card>
          ))}
        </div>
      )}
    </Section>
  );
}

// --------------------------------------------------------------------------------------------- process health
function ProcessSection({ p }: { p: ProgressData }) {
  const h = p.process_health;
  const rate = h.candidates_evaluated ? h.candidates_passed / h.candidates_evaluated : null;
  return (
    <Section title="Process health" note="Whether the research loop itself is productive and affordable.">
      <Tiles
        tiles={[
          { key: "cycles", label: "Improvement cycles", value: fmtNum(h.cycles_total), sub: `${fmtNum(h.cycles_completed)} completed`, href: "/history" },
          { key: "passed", label: "Candidates passing validation", value: `${fmtNum(h.candidates_passed)} of ${fmtNum(h.candidates_evaluated)}`, sub: rate == null ? null : `${fmtPct(rate, 0)} pass rate`, href: "/performance" },
          { key: "agent", label: "Agent spend, all time", value: fmtUsd(h.anthropic_usd_total), href: "/cost" },
          { key: "per", label: "Total cost per passing candidate", value: fmtUsd(h.cost_per_passed_candidate), sub: "agents and warehouse", href: "/cost" },
        ]}
      />
      {h.months.length > 1 && (
        <Card flush>
          <DataTable
            rows={h.months}
            rowKey={(m) => m.month}
            columns={[
              { key: "month", header: "Month", render: (m) => m.month, sort: (m) => m.month },
              { key: "cycles", header: "Cycles", align: "right", render: (m) => fmtNum(m.cycles), sort: (m) => m.cycles },
              { key: "passed", header: "Passed validation", align: "right", render: (m) => fmtNum(m.passed), sort: (m) => m.passed },
              { key: "cost", header: "Spend", align: "right", render: (m) => fmtUsd(m.cost_usd), sort: (m) => m.cost_usd },
            ]}
          />
        </Card>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------------------------------------ denominator
function DenominatorSection({ p }: { p: ProgressData }) {
  const d = p.denominator;
  if (!d) return null;
  return (
    <Section
      title="Everything that was tried"
      note="A best result means little without the number of attempts. Each validation test raises the margin the next candidate must clear; the holdout is read only by the promotion gate, a limited number of times."
    >
      <Tiles
        tiles={[
          { key: "since", label: "Tests since the last reset", value: fmtNum(d.tests_since_reset), sub: `definition ${shortVersion(d.definition_version)}`, href: links.definition(d.definition_version) },
          { key: "total", label: "Tests under this definition", value: fmtNum(d.tests_total), href: "/performance" },
          { key: "margin", label: "Margin the next candidate must clear", value: `${fmtDiff(d.next_margin, 4)}`, sub: "AUC over the reference" },
          { key: "holdout", label: "Holdout gates used", value: `${d.holdout_used} of ${d.holdout_budget}`, tone: d.holdout_used >= d.holdout_budget ? "warn" : null },
        ]}
      />
      <Card flush>
        <DataTable
          rows={d.candidates}
          rowKey={(c) => `${c.ref}-${c.ts}`}
          initialSort={{ key: "ts", dir: "desc" }}
          columns={[
            {
              key: "ref",
              header: "Candidate",
              render: (c) => (c.ref.startsWith("candidate:") ? <Link to={links.approval(c.ref)}>{refLabel(c.ref)}</Link> : <span>{refLabel(c.ref)}</span>),
              sort: (c) => c.ref,
            },
            { key: "auc", header: "Validation AUC", align: "right", render: (c) => <span className="num">{fmtAuc(c.auc, 4)}</span>, sort: (c) => c.auc },
            {
              key: "passed",
              header: "Result",
              render: (c) => (c.passed == null ? <Pill>unknown</Pill> : c.passed ? <Pill tone="good">passed</Pill> : <Pill tone="warn">did not pass</Pill>),
              sort: (c) => (c.passed ? 1 : 0),
            },
            { key: "ts", header: "When", render: (c) => <TimeAgo iso={c.ts} />, sort: (c) => c.ts },
          ]}
        />
      </Card>
    </Section>
  );
}

