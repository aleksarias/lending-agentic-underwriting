/** Every shadow-scoring run, one row per role scored: which model, under which definition, over how many applications. */
import { useModels } from "../../api/hooks";
import type { ShadowData } from "../../api/types";
import { fmtDateTime, fmtNum, fmtPct } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import { findByVersion } from "../Operate/models";
import { Card, DataTable, ModelBadge, Pill, TimeAgo, type Column } from "../ui";
import { ROLE_HELP, roleLabel } from "./roles";

type Run = ShadowData["runs"][number];

export function RunsTable({ runs }: { runs: Run[] }) {
  const models = useModels();
  const columns: Column<Run>[] = [
    {
      key: "at",
      header: "Scored",
      render: (r) => (
        <span className="nowrap" title={fmtDateTime(r.scored_at)}>
          <TimeAgo iso={r.scored_at} />
        </span>
      ),
      sort: (r) => r.scored_at,
    },
    {
      key: "role",
      header: "Role",
      render: (r) => (
        <span title={ROLE_HELP[r.role]}>
          <Pill tone={r.role === "serving" ? "accent" : "neutral"}>{roleLabel(r.role)}</Pill>
        </span>
      ),
      sort: (r) => r.role,
    },
    {
      key: "model",
      header: "Model",
      render: (r) => {
        const m = findByVersion(models.data, r.model_version, r.role === "serving");
        return m ? <ModelBadge model={m} /> : <span>v{r.model_version}</span>;
      },
      sort: (r) => Number(r.model_version),
    },
    { key: "def", header: "Definition of default", render: (r) => <DefBadge version={r.definition_version} /> },
    { key: "n", header: "Applications", align: "right", render: (r) => <span className="num">{fmtNum(r.n)}</span>, sort: (r) => r.n },
    {
      key: "mean",
      header: "Mean predicted default probability",
      align: "right",
      render: (r) => <span className="num">{fmtPct(r.mean_pd, 1)}</span>,
      sort: (r) => r.mean_pd,
    },
  ];
  return (
    <Card flush kind="measured">
      <DataTable rows={runs} columns={columns} rowKey={(r) => `${r.scored_at}-${r.role}-${r.model_version}`} initialSort={{ key: "at", dir: "desc" }} maxHeight={420} />
    </Card>
  );
}
