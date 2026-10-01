/** Names for protected classes and groups as they appear in fairness tests (keys come from config/protected_classes.yaml). */
import { titleCase } from "../../lib/format";

const CLASS_LABEL: Record<string, string> = {
  race_ethnicity: "Race and ethnicity",
  sex: "Sex",
  age_62_plus: "Age 62 and over",
};

export const classLabel = (cls: string) => CLASS_LABEL[cls] ?? titleCase(cls);

export function groupLabel(cls: string, group: string | null | undefined): string {
  if (group == null) return "Pooled";
  if (cls === "age_62_plus") return group === "true" ? "62 and over" : group === "false" ? "Under 62" : group;
  return titleCase(group);
}

/** "Hispanic applicants against White applicants": where a ratio comes from. */
export function comparison(cls: string, group: string, reference: string): string {
  const who = (g: string) => (cls === "age_62_plus" ? (g === "true" ? "Applicants aged 62 and over" : "Applicants under 62") : `${groupLabel(cls, g)} applicants`);
  return `${who(group)} against ${who(reference).replace(/^./, (c) => (cls === "age_62_plus" ? c.toLowerCase() : c))}`;
}
