/** Pipeline stages and recent runs for one version of the definition. */
import { usePipeline } from "../../api/hooks";
import type { DefinitionVersion, PipelineData } from "../../api/types";
import { fmtDateTime, fmtSeconds, titleCase } from "../../lib/format";
import { definitionLabel } from "../Definitions/labels";
import { StageList } from "../lists";
import { Card, DataTable, EmptyState, Pill, QueryView, type Column } from "../ui";

type Run = PipelineData["runs"][number];

const RUN_TONE: Record<string, "good" | "crit" | "neutral"> = { success: "good", failed: "crit" };

export function PipelineSection({ def, all }: { def: DefinitionVersion; all: DefinitionVersion[] }) {
  const pipeline = usePipeline(def.version);
  return (
    <QueryView query={pipeline} loadingHeight={200}>
      {(p) => {
        const builtHere = p.stages.filter((s) => s.last_run_at && s.definition_version === def.version);
        const shared = p.stages.filter((s) => s.last_run_at && s.definition_version && s.definition_version !== def.version);
        const other = shared[0] ? all.find((d) => d.version === shared[0].definition_version) : undefined;
        if (p.stages.every((s) => s.status === "never") && p.runs.length === 0) {
          return (
            <EmptyState title="The pipeline has never run for this definition">
              When the definition is applied, the pipeline builds labels, splits, the catalog, baselines and monitoring for it. Its stages and runs appear here.
            </EmptyState>
          );
        }
        const columns: Column<Run>[] = [
          { key: "stage", header: "Stage", render: (r) => titleCase(r.stage), sort: (r) => r.stage },
          { key: "status", header: "Result", render: (r) => <Pill tone={RUN_TONE[r.status] ?? "neutral"}>{r.status}</Pill>, sort: (r) => r.status },
          { key: "started", header: "Started (UTC)", render: (r) => fmtDateTime(r.started_at), sort: (r) => r.started_at },
          { key: "duration", header: "Duration", align: "right", render: (r) => fmtSeconds(r.duration_s), sort: (r) => r.duration_s },
        ];
        const failed = p.runs.filter((r) => r.status === "failed").length;
        return (
          <div className="definition-detail-pipeline">
            <Card title="Stages">
              <StageList stages={p.stages} />
              {shared.length > 0 && (
                <div className="xs muted" style={{ marginTop: 8 }}>
                  {shared.map((s) => titleCase(s.stage)).join(" and ")} last ran for {other ? definitionLabel(other) : "another definition"}: {shared.length === 1 ? "that stage is" : "those stages are"} shared by
                  every definition.
                </div>
              )}
              {!def.is_active && builtHere.length > 0 && (
                <div className="xs muted" style={{ marginTop: 8 }}>
                  This definition is not active, so the pipeline is not rebuilt for it. Stages show the state of its last build.
                </div>
              )}
            </Card>
            <div className="stack">
              <Card flush>
                <DataTable rows={p.runs} columns={columns} rowKey={(r) => `${r.stage}-${r.started_at}`} initialSort={{ key: "started", dir: "desc" }} empty={<EmptyState title="No runs recorded" />} maxHeight={420} />
              </Card>
              <div className="xs muted">
                {p.runs.length} recent run{p.runs.length === 1 ? "" : "s"}
                {failed ? `, ${failed} failed` : ""}.
              </div>
            </div>
          </div>
        );
      }}
    </QueryView>
  );
}
