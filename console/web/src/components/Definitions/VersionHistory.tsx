/** Every recorded version of the definition of default, newest activation first, with the labels it produced. */
import { Link, useNavigate } from "react-router-dom";
import type { DefinitionVersion } from "../../api/types";
import { fmtDateTime, fmtNum, fmtPct } from "../../lib/format";
import { DataTable, DefinitionBadge, Pill, links, type Column } from "../ui";
import { definitionRefOf } from "./labels";

export function VersionHistory({ defs }: { defs: DefinitionVersion[] }) {
  const navigate = useNavigate();
  const time = (iso: string | null) => (iso ? Date.parse(iso) : null);
  const columns: Column<DefinitionVersion>[] = [
    {
      key: "definition",
      header: "Definition",
      render: (d) => (
        <div className="stack definitions-wrap" style={{ gap: 3 }}>
          <span>
            <DefinitionBadge def={definitionRefOf(d)} />
          </span>
          <span className="xs muted mono">{d.name}</span>
        </div>
      ),
      sort: (d) => d.name,
    },
    {
      key: "from",
      header: "Active from (UTC)",
      render: (d) => (d.active_from ? fmtDateTime(d.active_from) : <span className="muted">never activated</span>),
      sort: (d) => time(d.active_from),
    },
    {
      key: "to",
      header: "Active to (UTC)",
      render: (d) => (d.is_active ? <Pill tone="accent" dot>Active now</Pill> : d.active_to ? fmtDateTime(d.active_to) : <span className="muted">none</span>),
      sort: (d) => (d.is_active ? Number.MAX_SAFE_INTEGER : time(d.active_to)),
    },
    { key: "by", header: "Activated by", render: (d) => d.activated_by ?? <span className="muted">not recorded</span>, sort: (d) => d.activated_by },
    { key: "eligible", header: "Eligible loans", align: "right", render: (d) => fmtNum(d.label_stats?.n_eligible), sort: (d) => d.label_stats?.n_eligible ?? null },
    { key: "defaults", header: "Defaults", align: "right", render: (d) => fmtNum(d.label_stats?.n_default), sort: (d) => d.label_stats?.n_default ?? null },
    { key: "rate", header: "Default rate", align: "right", render: (d) => fmtPct(d.label_stats?.default_rate), sort: (d) => d.label_stats?.default_rate ?? null },
    {
      key: "details",
      header: "Details",
      render: (d) => (
        <Link to={links.definition(d.version)} onClick={(e) => e.stopPropagation()}>
          Open
        </Link>
      ),
    },
  ];
  return (
    <DataTable
      rows={defs}
      columns={columns}
      rowKey={(d) => d.version}
      initialSort={{ key: "from", dir: "desc" }}
      onRowClick={(d) => navigate(links.definition(d.version))}
    />
  );
}
