/**
 * Screen 13 — Features lab. Answers: which engineered features have agents proposed, how do they screen under the
 * active definition, are any risky, and are they used in models? Feature SQL and reasoning are agent output (proposed);
 * the screen numbers are pipeline measurements.
 */
import { useSearchParams } from "react-router-dom";
import { useFeatures, useStatus } from "../api/hooks";
import { FeaturesView } from "../components/Features/FeaturesView";
import { ErrorState, Loading, Page } from "../components/ui";

export default function Features() {
  const q = useFeatures();
  const status = useStatus();
  const [params] = useSearchParams();
  const error = q.isError ? q.error : status.isError && !status.data ? status.error : null;
  return (
    <Page>
      {error ? (
        <ErrorState error={error} />
      ) : !q.data || !status.data ? (
        <Loading height={360} />
      ) : (
        <FeaturesView features={q.data} active={status.data.active_definition} initialQuery={params.get("q") ?? ""} />
      )}
    </Page>
  );
}
