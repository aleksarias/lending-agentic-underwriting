/** What the model relies on: feature importance, the model's features, and the reference it was compared with. */
import { Link } from "react-router-dom";
import type { EvaluationDetail, ModelVersion } from "../../api/types";
import { fmtAuc } from "../../lib/format";
import { FeatureImportance } from "../ModelDetail/FeatureImportance";
import { modelTypeLabel, plural } from "../Models/shared";
import { Card, KeyValue, ModelBadge, Section, links } from "../ui";
import "./evaluation.css";

export function FeaturesTab({ e, models }: { e: EvaluationDetail; models: ModelVersion[] | undefined }) {
  const eng = new Set(e.model.engineered);
  const ref = e.reference;
  const refModel =
    ref.model_version != null ? models?.find((m) => m.model.label === (ref.kind === "champion" ? `prod v${ref.model_version}` : `v${ref.model_version}`))?.model : undefined;
  return (
    <div className="evaluation-panel">
      <Section title="Feature importance">
        <FeatureImportance rows={e.feature_importance} engineered={e.model.engineered} modelType={e.model.model_type} />
      </Section>

      <Section title={`Model features (${e.model.features.length})`} note={`${modelTypeLabel(e.model.model_type)}; ${plural(e.model.engineered.length, "engineered feature")}.`}>
        <Card kind="measured">
          {e.model.features.length === 0 ? (
            <span className="muted small">No features recorded.</span>
          ) : (
            <ul className="models-chips">
              {e.model.features.map((f) =>
                eng.has(f) ? (
                  <li key={f} className="models-chip">
                    {f}
                    <span className="tag">engineered</span>
                  </li>
                ) : (
                  <li key={f}>
                    <Link className="models-chip" to={links.variable(f)}>
                      {f}
                    </Link>
                  </li>
                ),
              )}
            </ul>
          )}
        </Card>
      </Section>

      <Section title="Reference" note="The model this candidate had to beat by the required margin.">
        <Card kind="measured">
          <KeyValue
            items={[
              [
                "Compared with",
                ref.kind === "none" ? (
                  <span key="k">Nothing: this evaluation sets the reference for later candidates</span>
                ) : refModel ? (
                  <span key="k" className="row" style={{ gap: 6 }}>
                    <span>{ref.kind}</span>
                    <ModelBadge model={refModel} />
                  </span>
                ) : (
                  <span key="k">
                    {ref.kind}
                    {ref.model_version ? ` v${ref.model_version}` : ""}
                  </span>
                ),
              ],
              ["Reference validation AUC", <span key="a" className="num">{fmtAuc(ref.auc)}</span>],
              ["Validation AUC, this model", <span key="v" className="num">{fmtAuc(e.val_auc)}</span>],
              ["Required margin", <span key="m" className="num">{fmtAuc(e.required_margin)}</span>],
            ]}
          />
        </Card>
      </Section>
    </div>
  );
}
