/**
 * Production readiness: what must be true, and who must sign, before the decision API decides on real applications.
 * The system gathers evidence for each item; named people sign at a terminal (`lau readiness sign`). Read-only here:
 * the console never records a sign-off, and nothing on this page claims compliance.
 */
import { useReadiness } from "../api/hooks";
import type { ReadinessItem } from "../api/types";
import { Banner, Card, CodeBlock, Page, PageHeader, Pill, QueryView, Section, TimeAgo } from "../components/ui";

const STATE = { signed: { tone: "good", label: "Signed" }, open: { tone: "warn", label: "Open" }, declined: { tone: "crit", label: "Declined" } } as const;
const ROLE: Record<string, string> = {
  data_owner: "Data owner",
  counsel: "Counsel",
  credit_policy: "Credit policy",
  model_validation: "Model validation",
  compliance: "Compliance",
  security: "Security",
  operations: "Operations",
  finance: "Finance",
};

function ItemCard({ item }: { item: ReadinessItem }) {
  const st = STATE[item.state];
  return (
    <Card>
      <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <Pill tone={st.tone}>{st.label}</Pill>
        <strong>{item.title}</strong>
        <span className="mono xs muted">{item.id}</span>
      </div>
      <p className="small" style={{ margin: "6px 0 10px" }}>{item.detail}</p>
      <div className="grid cols-2">
        <div>
          <div className="xs muted" style={{ marginBottom: 4 }}>Evidence the system gathered (a prerequisite, not a signature)</div>
          <ul className="plain small">
            {item.evidence.map((e) => (
              <li key={e.label}>
                <Pill tone={e.met ? "good" : "neutral"}>{e.met ? "yes" : "not yet"}</Pill> {e.label} <span className="xs muted">({e.detail})</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="xs muted" style={{ marginBottom: 4 }}>Sign-offs</div>
          <ul className="plain small">
            {item.signoffs.map((r) => (
              <li key={r.role}>
                <strong>{ROLE[r.role] ?? r.role}</strong>:{" "}
                {r.decision ? (
                  <>
                    <Pill tone={r.decision === "sign" ? "good" : r.decision === "decline" ? "crit" : "neutral"}>{r.decision === "sign" ? "signed" : r.decision === "decline" ? "declined" : "revoked"}</Pill> by {r.signer}{" "}
                    <span className="xs muted">
                      <TimeAgo iso={r.ts} />
                    </span>
                    {r.note && <div className="xs muted">{r.note}</div>}
                  </>
                ) : (
                  <span className="muted">not signed</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

export default function Readiness() {
  const q = useReadiness();
  return (
    <Page>
      <QueryView query={q} loadingHeight={320}>
        {(d) => (
          <>
            <PageHeader eyebrow="Decide and operate" title="Production readiness" summary={d.statement} />
            <Banner tone={d.ready ? "good" : "neutral"} title={d.ready ? "Every item is signed" : "Sign-offs are recorded at a terminal, by the named reviewer"}>
              A reviewer signs, declines or withdraws a sign-off for their role:
              <CodeBlock>{"lau readiness status\nlau readiness sign <item> --role <role>\nlau readiness decline <item> --role <role>"}</CodeBlock>
              The evidence below is refreshed by the daily evidence run.
            </Banner>
            <Section title="Checklist">
              <div className="stack">
                {d.items.map((item) => (
                  <ItemCard key={item.id} item={item} />
                ))}
              </div>
            </Section>
          </>
        )}
      </QueryView>
    </Page>
  );
}
