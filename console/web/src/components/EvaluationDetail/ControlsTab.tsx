/** Leakage screen of the model's features, and the quality of the reason codes given to declined applications. */
import { Link } from "react-router-dom";
import type { EvaluationDetail, Tile } from "../../api/types";
import { fmtNum, fmtPct } from "../../lib/format";
import { HBars } from "../Models/shared";
import type { Limits } from "../Performance/thresholds";
import { Banner, Card, DataTable, EmptyState, Pill, Section, Tiles, links, type Column } from "../ui";
import "./evaluation.css";

const RISK_ORDER = { high: 0, medium: 1, low: 2 } as const;

export function ControlsTab({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  return (
    <div className="evaluation-panel">
      <LeakageSection e={e} limits={limits} />
      <ReasonCodesSection e={e} limits={limits} />
    </div>
  );
}

function LeakageSection({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const rows = [...e.leakage].sort((a, b) => (RISK_ORDER[a.risk as keyof typeof RISK_ORDER] ?? 3) - (RISK_ORDER[b.risk as keyof typeof RISK_ORDER] ?? 3));
  const risky = rows.filter((r) => r.risk !== "low").length;
  const cols: Column<(typeof rows)[number]>[] = [
    {
      key: "column",
      header: "Feature",
      render: (r) => (
        <Link className="mono" to={links.variable(r.column)}>
          {r.column}
        </Link>
      ),
      sort: (r) => r.column,
    },
    {
      key: "risk",
      header: "Leakage risk",
      render: (r) => <Pill tone={r.risk === "high" ? "crit" : r.risk === "medium" ? "warn" : "neutral"}>{r.risk}</Pill>,
      sort: (r) => -(RISK_ORDER[r.risk as keyof typeof RISK_ORDER] ?? 3),
    },
    { key: "reasons", header: "Why", render: (r) => (r.reasons.length ? r.reasons.join("; ") : <span className="muted">no concern found</span>) },
  ];
  return (
    <Section
      title="Leakage screen"
      note={`Leakage means a feature carries information that is only known after the lending decision, or looks like the outcome itself. A high-risk feature fails the check.${limits.singleFeatureAucMax != null ? ` A feature that alone predicts default with AUC above ${fmtNum(limits.singleFeatureAucMax, 2)} is flagged.` : ""}`}
    >
      {rows.length === 0 ? (
        <EmptyState title="No leakage results recorded" />
      ) : (
        <>
          <div className="small">
            {risky ? `${risky} of ${rows.length} model features have medium or high leakage risk.` : `None of the ${rows.length} model features has a medium or high leakage risk.`}
          </div>
          <Card flush kind="measured">
            <DataTable rows={rows} columns={cols} rowKey={(r) => r.column} maxHeight={rows.length > 12 ? 360 : undefined} />
          </Card>
        </>
      )}
    </Section>
  );
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function ReasonCodesSection({ e, limits }: { e: EvaluationDetail; limits: Limits }) {
  const q = e.reason_codes.quality as Record<string, unknown>;
  const topN = limits.reasonTopN;
  const tiles: Tile[] = [];
  const add = (key: string, label: string, v: number | null, fmt: (x: number) => string, sub?: string) => {
    if (v != null) tiles.push({ key, label, value: fmt(v), sub });
  };
  add("n", "Declined applications sampled", num(q.n_declined), (v) => fmtNum(v), "reason codes are generated for this sample");
  add("any", "With at least one reason", num(q.coverage_any), (v) => fmtPct(v, 1), "share of sampled declines that got a reason");
  add("full", topN ? `With all ${topN} reasons` : "With a full set of reasons", num(q.coverage_full), (v) => fmtPct(v, 1));
  add("flag", "Reasons citing a flagged feature", num(q.flagged_feature_share), (v) => fmtPct(v, 1), "flagged proxies or prohibited features");
  add("top", "Most common top reason", num(q.top_reason_share), (v) => fmtPct(v, 1), "share of declines that share it");

  const top = q.top_reasons && typeof q.top_reasons === "object" ? Object.entries(q.top_reasons as Record<string, unknown>).flatMap(([k, v]) => (num(v) != null ? [[k, num(v) as number] as [string, number]] : [])) : [];
  const sample = e.reason_codes.sample;
  const byApp = new Map<string, EvaluationDetail["reason_codes"]["sample"]>();
  for (const s of sample) byApp.set(s.application_id, [...(byApp.get(s.application_id) ?? []), s]);
  const apps = [...byApp.entries()].map(([id, reasons]) => ({ id, reasons: [...reasons].sort((a, b) => a.rank - b.rank) }));
  const maxRank = Math.max(0, ...sample.map((s) => s.rank));
  const fallback = (s: { feature: string; reason_text: string }) => s.reason_text.trim().toLowerCase() === s.feature.replace(/_/g, " ").toLowerCase();
  const fallbacks = sample.filter(fallback);
  const fallbackFeatures = [...new Set(fallbacks.map((s) => s.feature))];

  const cols: Column<(typeof apps)[number]>[] = [
    { key: "id", header: "Declined application", render: (a) => <span className="mono xs">{a.id}</span>, sort: (a) => a.id },
    ...Array.from({ length: maxRank }, (_, i) => ({
      key: `r${i + 1}`,
      header: `Reason ${i + 1}`,
      render: (a: (typeof apps)[number]) => {
        const r = a.reasons.find((x) => x.rank === i + 1);
        if (!r) return <span className="muted">—</span>;
        return (
          <span className="evaluation-reason">
            {r.reason_text}
            <span className="feature">{r.feature}</span>
            {fallback(r) && <span className="evaluation-flag">text is the feature name</span>}
          </span>
        );
      },
    })),
  ];

  return (
    <Section
      title="Reason codes"
      note="The principal reasons given to an applicant who is declined. The check requires nearly every decline to get a reason and none to cite a flagged or prohibited feature."
    >
      {tiles.length === 0 && sample.length === 0 ? (
        <EmptyState title="No reason-code results recorded" />
      ) : (
        <>
          {tiles.length > 0 && <Tiles tiles={tiles} />}
          {top.length > 0 && (
            <Card title="Top reason given to declined applicants" kind="measured">
              <HBars
                title="Share of declined applications by their top reason"
                rows={top.map(([k, v]) => ({
                  key: k,
                  label: (
                    <Link className="mono" to={links.variable(k)}>
                      {k}
                    </Link>
                  ),
                  value: v,
                }))}
                format={(v) => fmtPct(v, 1)}
                footnote="Each declined application counts once, under its highest-ranked reason."
              />
            </Card>
          )}
          {fallbacks.length > 0 && (
            <Banner tone="warn" title="Some reason text is only the feature name">
              {fallbacks.length} of the {sample.length} reasons in the sample use the feature name itself as their text ({fallbackFeatures.join(", ")}), which usually means the feature has no
              plain-language description in the data catalog. Adverse-action notices need wording an applicant can read.
            </Banner>
          )}
          {apps.length > 0 && (
            <Card flush kind="measured">
              <div className="evaluation-sample">
                <DataTable rows={apps} columns={cols} rowKey={(a) => a.id} maxHeight={420} />
              </div>
            </Card>
          )}
          <div className="xs muted">Sample of {apps.length} declined applications, each with its ranked reasons as they would be given in the notice. The small code under each reason is the feature behind it.</div>
        </>
      )}
    </Section>
  );
}
