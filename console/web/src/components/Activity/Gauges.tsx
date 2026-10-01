/** Budget gauges for the running cycle: validation tests, agent spend and wall clock against their caps. */
import { fmtUsd } from "../../lib/format";
import "./activity.css";
import { Link } from "react-router-dom";
import type { Gauge } from "../../api/types";
import { Card, Meter } from "../ui";

const EXPLAIN: Record<string, { text: string; to?: string; link?: string }> = {
  experiments: {
    text: "Candidate evaluations against the validation set. Each one raises the margin the next candidate must clear.",
    to: "/performance",
    link: "Validation test ledger",
  },
  anthropic_usd: {
    text: "Agent spend recorded by the orchestrator at the end of each agent run.",
    to: "/cost",
    link: "Spend detail",
  },
  wall_clock: {
    text: "Minutes since the cycle started. The orchestrator ends the cycle at this cap.",
  },
};

export function Gauges({ gauges }: { gauges: Gauge[] }) {
  if (!gauges.length) return null;
  return (
    <div className="grid cols-3">
      {gauges.map((g) => {
        const ex = EXPLAIN[g.key];
        return (
          <Card key={g.key} kind="measured">
            <div className="activity-gauge">
              <Meter label={g.label} used={g.used} cap={g.cap} unit={` ${g.unit}`} format={g.unit === "USD" ? (v) => fmtUsd(v) : undefined} />
              {ex && <div className="xs muted">{ex.text}</div>}
              {ex?.to && (
                <div className="xs">
                  <Link to={ex.to}>{ex.link}</Link>
                </div>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
