/** What the model is: type, hyperparameters, features (raw and engineered, with the SQL behind each engineered one). */
import { useState } from "react";
import { Link } from "react-router-dom";
import type { ModelCard } from "../../api/types";
import { modelTypeLabel, plural } from "../shared";
import { Card, CodeBlock, EmptyState, KeyValue, KindTag, Section, links } from "../ui";
import "./modeldetail.css";

const FEATURE_PREVIEW = 30;

function paramText(v: unknown): string {
  return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
}

export function DescriptionSection({ card, trainedUnder }: { card: ModelCard; trainedUnder?: string }) {
  const d = card.description;
  const [all, setAll] = useState(false);
  if (!d) {
    return (
      <Section title="Description">
        <EmptyState title="No description recorded">
          Features and parameters are recorded when the harness evaluates a version. This version has no evaluation yet, so only its registry tags are known (see
          the end of this page).
        </EmptyState>
      </Section>
    );
  }
  const engineeredNames = new Set(d.engineered);
  const features = all ? d.features : d.features.slice(0, FEATURE_PREVIEW);
  const params = Object.entries(d.params);
  return (
    <Section title="Description" note="As recorded by the harness when it last evaluated this version.">
      <div className="grid split">
        <Card title="Model">
          <KeyValue
            items={[
              ["Type", <span key="t">{modelTypeLabel(d.model_type)}</span>],
              ["Registered as", <span key="n" className="mono">{card.model.name}</span>],
              ["Trained under", trainedUnder ?? <span className="muted">not on the benchmark ledger</span>],
              ["Features", `${plural(d.features.length, "feature")}${d.engineered.length ? `, ${d.engineered.length} engineered` : ""}`],
            ]}
          />
          {params.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="card-title" style={{ marginBottom: 6 }}>
                Hyperparameters
              </div>
              <dl className="modeldetail-params">
                {params.map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{paramText(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </Card>
        <Card title={`Features (${d.features.length})`}>
          {d.features.length === 0 ? (
            <span className="muted small">No features recorded.</span>
          ) : (
            <>
              <ul className="models-chips">
                {features.map((f) =>
                  engineeredNames.has(f) ? (
                    <li key={f} className="models-chip">
                      {f}
                      <span className="tag">engineered</span>
                    </li>
                  ) : (
                    <li key={f}>
                      <Link className="models-chip" to={links.variable(f)} title="Open in the data catalog">
                        {f}
                      </Link>
                    </li>
                  ),
                )}
              </ul>
              {d.features.length > FEATURE_PREVIEW && (
                <div style={{ marginTop: 8 }}>
                  <button className="btn small" type="button" onClick={() => setAll((x) => !x)} aria-expanded={all}>
                    {all ? "Show fewer" : `Show all ${d.features.length} features`}
                  </button>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
      {card.engineered.length > 0 && (
        <Card title="Engineered features" kind="proposed">
          <div className="small muted" style={{ marginBottom: 10 }}>
            Engineered features are proposed by agents: the SQL is the expression the pipeline runs and the rationale is the agent’s own explanation. <KindTag kind="proposed" />
          </div>
          <div className="modeldetail-engineered">
            {card.engineered.map((e) => (
              <div className="item" key={e.name}>
                <div className="name">{e.name}</div>
                {e.expression ? <CodeBlock>{e.expression}</CodeBlock> : <span className="small muted">The expression is not in the feature registry.</span>}
                {e.rationale && <div className="small">{e.rationale}</div>}
              </div>
            ))}
          </div>
        </Card>
      )}
    </Section>
  );
}
