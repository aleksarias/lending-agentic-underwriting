/** One definition of default in the model registry: a header with the definition, then its model versions. */
import { Link, useNavigate } from "react-router-dom";
import type { DefinitionRef, DefinitionVersion, ModelVersion } from "../../api/types";
import { fmtAuc, fmtDate, fmtDateTime, shortVersion } from "../../lib/format";
import { DataTable, DefinitionBadge, ModelBadge, Pill, Section, links, type Column } from "../ui";
import { StatusPill, STATUS_ORDER, StopRowClick, modelTypeLabel, plural } from "./shared";

export interface ModelGroupProps {
  /** definition_version of the group; "" when a model has no definition recorded */
  version: string;
  def: DefinitionRef | undefined;
  detail: DefinitionVersion | undefined;
  isActive: boolean;
  models: ModelVersion[];
  /** key of the best known model on the primary benchmark, when the benchmark ledger exists */
  bestKnownKey: string | null;
  /** how many models the benchmark ledger scored (the denominator behind "best known") */
  scoredCount: number;
  /** model key -> short data version the model was trained on (from the benchmark ledger) */
  dataVersionByKey: Record<string, string>;
}

export function ModelGroup(props: ModelGroupProps) {
  const navigate = useNavigate();
  const { models, def, detail, isActive } = props;
  const title = def ? def.summary : props.version ? `Definition ${shortVersion(props.version)}` : "No definition recorded";
  const counts = STATUS_ORDER.map((s) => [s, models.filter((m) => m.status === s).length] as const).filter(([, n]) => n > 0);

  const columns: Column<ModelVersion>[] = [
    {
      key: "model",
      header: "Model",
      render: (m) => (
        <span className="row" style={{ gap: 6 }}>
          <ModelBadge model={m.model} />
          {props.bestKnownKey === m.model.key && (
            <span title={`Highest AUC on the primary benchmark, among ${props.scoredCount} models scored on the same loans`}>
              <Pill tone="accent">best known</Pill>
            </span>
          )}
        </span>
      ),
      sort: (m) => Number(m.model.version),
    },
    { key: "status", header: "Status", render: (m) => <StatusPill status={m.status} />, sort: (m) => STATUS_ORDER.indexOf(m.status) },
    {
      key: "aliases",
      header: "Aliases",
      render: (m) =>
        m.aliases.length ? (
          <span className="models-aliases">
            {m.aliases.map((a) => (
              <code key={a} className="mono xs">
                {a}
              </code>
            ))}
          </span>
        ) : (
          <span className="faint">none</span>
        ),
    },
    {
      key: "type",
      header: "Type",
      render: (m) => (
        <span>
          {modelTypeLabel(m.model_type)}
          {m.n_features != null && <span className="models-cell-sub">{plural(m.n_features, "feature")}</span>}
        </span>
      ),
      sort: (m) => m.model_type,
    },
    {
      key: "auc",
      header: "Validation AUC",
      align: "right",
      render: (m) =>
        m.val_auc == null ? (
          <span className="muted" title="The harness has not evaluated this version">
            not evaluated
          </span>
        ) : (
          <span className="num">
            <StopRowClick>
              <Link to={links.model(m.model.name, m.model.version)} title="Open the model and its evaluations">
                {fmtAuc(m.val_auc)}
              </Link>
            </StopRowClick>
            {props.dataVersionByKey[m.model.key] && <span className="models-cell-sub">data {props.dataVersionByKey[m.model.key]}</span>}
          </span>
        ),
      sort: (m) => m.val_auc,
    },
    {
      key: "passed",
      header: "Passed validation",
      render: (m) =>
        m.passed_validation == null ? (
          <Pill>not evaluated</Pill>
        ) : m.passed_validation ? (
          <span title={m.status === "baseline" ? "Every harness check passed. A baseline has no earlier reference to beat." : "Every harness check passed, including the margin over the reference."}>
            <Pill tone="good">passed</Pill>
          </span>
        ) : (
          <span title="At least one harness check failed. Open the model to see its evaluation.">
            <Pill tone="warn">did not pass</Pill>
          </span>
        ),
      sort: (m) => (m.passed_validation == null ? -1 : m.passed_validation ? 1 : 0),
    },
    {
      key: "author",
      header: "Author, cycle",
      render: (m) => (
        <span>
          {m.author ?? <span className="faint">—</span>}
          <span className="models-cell-sub">
            {m.cycle_id ? (
              <StopRowClick>
                <Link className="mono nowrap" to={links.cycle(m.cycle_id)} title="The improvement cycle that registered this version">
                  {m.cycle_id}
                </Link>
              </StopRowClick>
            ) : (
              <span title="Trained by the pipeline, not by an improvement cycle">no cycle (pipeline)</span>
            )}
          </span>
        </span>
      ),
      sort: (m) => m.author,
    },
    {
      key: "created",
      header: "Created (UTC)",
      render: (m) => <span className="small">{fmtDateTime(m.created_at)}</span>,
      sort: (m) => m.created_at,
    },
  ];

  return (
    <Section
      title={title}
      right={
        <span className="row" style={{ gap: 8 }}>
          <DefinitionBadge def={def} version={props.version || null} />
          {isActive ? <Pill tone="accent">active definition</Pill> : props.version ? <Pill tone="neutral">replaced</Pill> : null}
        </span>
      }
      note={
        <span className="models-group-note">
          {plural(models.length, "version")}
          {counts.length > 0 && ` (${counts.map(([s, n]) => `${n} ${s}`).join(", ")})`}.{" "}
          {isActive
            ? "New candidates are evaluated against this definition."
            : detail?.active_to
              ? `Replaced on ${fmtDate(detail.active_to)} (UTC). Its models stay in the registry and on the benchmark ledger; only candidates of the active definition are sent for approval.`
              : "Not the active definition."}
        </span>
      }
    >
      <DataTable
        rows={models}
        columns={columns}
        rowKey={(m) => m.model.key}
        initialSort={{ key: "model", dir: "desc" }}
        onRowClick={(m) => navigate(links.model(m.model.name, m.model.version))}
      />
    </Section>
  );
}
