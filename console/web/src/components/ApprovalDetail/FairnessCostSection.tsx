/** Fairness (minimum adverse impact ratio) and what the research cycle that produced the candidate cost. */
import type { EvidencePacket, Tile } from "../../api/types";
import { fmtAuc, fmtUsd } from "../../lib/format";
import { Section, Tiles, links } from "../ui";

export interface CycleCost {
  cycleId: string | null;
  /** agent spend recorded on the cycle itself, used when the packet has no total */
  anthropicUsd: number | null;
}

export function FairnessCostSection({ p, minAirLimit, cycle }: { p: EvidencePacket; minAirLimit: number | null; cycle: CycleCost }) {
  const air = p.fairness_min_air;
  const airTone = air == null || minAirLimit == null ? null : air >= minAirLimit ? "good" : "crit";
  const cost: Tile =
    p.cost_usd != null
      ? { key: "cost", label: "Cost of the cycle", value: fmtUsd(p.cost_usd), sub: "agents and warehouse, whole cycle", href: cycle.cycleId ? links.cycle(cycle.cycleId) : "/cost" }
      : cycle.anthropicUsd != null
        ? { key: "cost", label: "Cost of the cycle", value: fmtUsd(cycle.anthropicUsd), sub: "agent spend recorded on the cycle; warehouse cost not attributed", href: cycle.cycleId ? links.cycle(cycle.cycleId) : "/cost" }
        : { key: "cost", label: "Cost of the cycle", value: "Not recorded", sub: cycle.cycleId ? "no cost rows for this cycle" : "the cycle is not known", href: cycle.cycleId ? links.cycle(cycle.cycleId) : "/cost" };
  return (
    <Section title="Fairness and cost" note="Adverse impact is measured by the harness on the validation window; cost is what the cycle that proposed this candidate spent.">
      <Tiles
        tiles={[
          {
            key: "air",
            label: "Minimum adverse impact ratio",
            value: fmtAuc(air, 3),
            sub: air == null ? "not measured" : minAirLimit != null ? `${air >= minAirLimit ? "at or above" : "below"} the limit of ${fmtAuc(minAirLimit, 2)}` : "lowest ratio across protected groups",
            tone: airTone,
            href: "/fairness",
          },
          cost,
        ]}
      />
    </Section>
  );
}
