/**
 * Screen 19 — Cost. Answers: how much has been spent this month against the hard stop, where did it go (day, cycle,
 * agent), and how much of it is estimated? Agent spend is what the Anthropic API reported per run; Databricks spend is
 * an estimate because billing actuals are not readable by the console identity.
 */
import { useCost, useStatus } from "../api/hooks";
import { CostView } from "../components/Cost/CostView";
import { ErrorState, Loading, Page } from "../components/ui";

export default function Cost() {
  const q = useCost();
  const status = useStatus();
  return (
    <Page>
      {q.isError ? <ErrorState error={q.error} /> : !q.data ? <Loading height={360} /> : <CostView c={q.data} status={status.data} />}
    </Page>
  );
}
