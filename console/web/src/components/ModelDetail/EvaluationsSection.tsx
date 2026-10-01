/** The harness evaluations of this model version. */
import type { ModelCard } from "../../api/types";
import { EvaluationsTable } from "../Performance/EvaluationsTable";
import { Card, EmptyState, Section } from "../ui";

export function EvaluationsSection({ card }: { card: ModelCard }) {
  return (
    <Section
      title="Evaluations"
      note="Validation results from the harness. The required margin grows with every validation test under the same definition, so later candidates face a higher bar."
    >
      {card.evaluations.length === 0 ? (
        <EmptyState title="Not evaluated">
          The harness has not evaluated this version, so there is no validation result, no checks, and it cannot reach the holdout gate. A candidate is evaluated
          when an improvement cycle submits it.
        </EmptyState>
      ) : (
        <Card flush kind="measured">
          <EvaluationsTable rows={card.evaluations} />
        </Card>
      )}
    </Section>
  );
}
