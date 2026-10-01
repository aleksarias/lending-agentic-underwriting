/** Every promotion, newest first: what was promoted, under which definition, what it replaced and whether it serves. */
import { Link } from "react-router-dom";
import { useModels } from "../../api/hooks";
import type { Promotion } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { DefBadge } from "../Operate/definitions";
import { findByVersion } from "../Operate/models";
import { Card, DataTable, ModelBadge, Pill, TimeAgo, links, type Column } from "../ui";

export function PromotionsTable({ rows }: { rows: Promotion[] }) {
  const models = useModels();
  const production = (v: string) => {
    const m = findByVersion(models.data, v, true);
    return m ? <ModelBadge model={m} /> : <span>production v{v}</span>;
  };
  const columns: Column<Promotion>[] = [
    {
      key: "ts",
      header: "When",
      render: (r) => (
        <span className="nowrap" title={fmtDateTime(r.ts)}>
          <TimeAgo iso={r.ts} />
        </span>
      ),
      sort: (r) => r.ts,
    },
    {
      key: "candidate",
      header: "Promoted candidate",
      render: (r) => (
        <Link to={links.approval(`candidate:${r.candidate_model_version}`)}>v{r.candidate_model_version} evidence</Link>
      ),
      sort: (r) => Number(r.candidate_model_version),
    },
    { key: "production", header: "Became", render: (r) => production(r.production_model_version), sort: (r) => Number(r.production_model_version) },
    { key: "definition", header: "Definition of default", render: (r) => <DefBadge version={r.definition_version} /> },
    {
      key: "previous",
      header: "Replaced",
      render: (r) => (r.previous_champion_version ? production(r.previous_champion_version) : <span className="muted">no earlier champion</span>),
    },
    {
      key: "serving",
      header: "Effect",
      render: (r) => (r.serving ? <Pill tone="good">Switched serving</Pill> : <Pill>Champion; its rollout decides serving</Pill>),
      sort: (r) => (r.serving ? 1 : 0),
    },
    { key: "approval", header: "Approval", render: (r) => <span className="mono xs">{r.approval_id || "—"}</span> },
  ];
  return (
    <Card flush>
      <DataTable rows={rows} columns={columns} rowKey={(r) => r.promotion_id} initialSort={{ key: "ts", dir: "desc" }} />
    </Card>
  );
}
