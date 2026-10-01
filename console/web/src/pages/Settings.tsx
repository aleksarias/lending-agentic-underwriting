/**
 * Screen 20 — Reports and settings. Read-only configuration (thresholds, budgets, models, protected classes),
 * benchmark definitions, config versions and access checks. Changes go through git and the CLI and are versioned.
 */
import { useSettings } from "../api/hooks";
import { SettingsView } from "../components/Settings/SettingsView";
import { ErrorState, Loading, Page } from "../components/ui";

export default function Settings() {
  const q = useSettings();
  return <Page>{q.isError ? <ErrorState error={q.error} /> : !q.data ? <Loading height={360} /> : <SettingsView s={q.data} />}</Page>;
}
