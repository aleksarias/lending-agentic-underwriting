/** Wording and tiles for the model registry screen, computed from the registry and the benchmark ledger. */
import type { ModelRef, ModelVersion, ProgressData, Tile } from "../../api/types";
import { fmtAuc } from "../../lib/format";
import { links } from "../ui";
import { plural } from "../shared";

export function summarySentence(
  list: ModelVersion[],
  nGroups: number,
  hasActive: boolean,
  challenger: ModelRef | undefined,
  serving: ModelRef | undefined,
  bestKnown: ModelRef | null,
): string {
  const parts = [`${plural(list.length, "version")} under ${plural(nGroups, "definition")}`];
  if (hasActive) {
    if (challenger) {
      const isBest = bestKnown?.key === challenger.key;
      parts.push(`${challenger.label} is the challenger for the active definition${isBest ? " and the best known model" : ""}`);
    } else {
      parts.push("no challenger is registered for the active definition");
    }
  }
  if (bestKnown && bestKnown.key !== challenger?.key) parts.push(`the best known model on the benchmark is ${bestKnown.label}`);
  parts.push(serving ? `${serving.label} is serving` : "nothing is serving");
  return `${parts.join("; ")}.`;
}

export function registryTiles(
  list: ModelVersion[],
  challenger: ModelVersion | undefined,
  serving: ModelVersion | undefined,
  champion: ModelVersion | undefined,
  bestKnown: ModelRef | null,
  progress: ProgressData | undefined,
): Tile[] {
  const out: Tile[] = [];
  out.push(
    serving
      ? { key: "serving", label: "Making decisions", value: serving.model.label, sub: "serving", tone: "good", href: links.model(serving.model.name, serving.model.version) }
      : {
          key: "serving",
          label: "Making decisions",
          value: "Legacy score",
          sub: champion ? `${champion.model.label} is champion but not serving` : "No model has been promoted yet",
          tone: "warn",
        },
  );
  if (challenger) {
    const beaten = bestKnown && bestKnown.key !== challenger.model.key;
    out.push({
      key: "challenger",
      label: "Challenger, active definition",
      value: challenger.model.label,
      sub: `${challenger.passed_validation == null ? "not evaluated" : challenger.passed_validation ? "passed validation" : "did not pass validation"}${beaten ? `; not the best known model` : ""}`,
      tone: beaten ? "warn" : null,
      href: links.model(challenger.model.name, challenger.model.version),
    });
  }
  if (bestKnown) {
    const matrix = progress?.benchmark;
    const primary = matrix?.primary_definition;
    const row = matrix?.rows.find((r) => r.model.key === bestKnown.key);
    const cell = primary ? row?.metrics[primary] : undefined;
    const def = matrix?.definitions.find((d) => d.key === primary);
    const scored = (matrix?.rows ?? []).filter((r) => r.model.kind !== "reference").length;
    out.push({
      key: "best",
      label: "Best known model",
      value: bestKnown.label,
      sub: cell && def ? `AUC ${fmtAuc(cell.auc)} on the ${def.dpd} DPD benchmark; best of ${scored} models scored on the same loans` : "on the benchmark ledger",
      href: "/progress",
    });
  }
  const baselines = list.filter((m) => m.status === "baseline").length;
  out.push({ key: "versions", label: "Registered versions", value: String(list.length), sub: `${baselines} baseline${baselines === 1 ? "" : "s"}, ${list.length - baselines} other` });
  return out;
}
