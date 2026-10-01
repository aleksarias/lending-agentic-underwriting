/** Defensive readers for the decision example, whose shape the API types only as a record. */
export const asRecord = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
export const asNumber = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const asString = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
export const asBoolean = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
export const asArray = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export interface ReasonCode {
  rank: number;
  feature: string;
  text: string;
}

export function readReasonCodes(v: unknown): ReasonCode[] {
  return asArray(v)
    .map((item, i) => {
      const r = asRecord(item);
      return {
        rank: asNumber(r.rank) ?? i + 1,
        feature: asString(r.feature) ?? "unknown feature",
        text: asString(r.text) ?? asString(r.statement) ?? "No statement",
      };
    })
    .sort((a, b) => a.rank - b.rank);
}
