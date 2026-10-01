/**
 * Matching registry models across payloads that do not always spell the model name the same way (the local fixture uses
 * the short name "pd_candidates", Databricks the qualified "catalog.schema.pd_candidates"), so links always go to a model
 * that exists.
 */
import { useMemo } from "react";
import { useModels } from "../../api/hooks";
import type { ModelRef, ModelVersion } from "../../api/types";

type Keyed = Pick<ModelRef, "key" | "name" | "version">;

const tail = (name: string) => name.split(".").pop() ?? name;

/** True when both refer to the same registered model version, ignoring the catalog and schema prefix of the name. */
export function sameModel(a: Keyed, b: Keyed): boolean {
  if (a.key === b.key) return true;
  if (!a.version || a.version !== b.version) return false;
  return tail(a.name) === tail(b.name);
}

/** The model ref the registry knows for `model`, or `model` itself while the registry list is loading or has no match. */
export function useResolvedModel(model: ModelRef): ModelRef {
  const q = useModels();
  return useMemo(() => q.data?.find((v) => sameModel(v.model, model))?.model ?? model, [q.data, model]);
}

/**
 * A registry version by number. Candidate and production versions are numbered separately, so the role decides which
 * model is meant: production champions are the serving model, everything else lives in the candidate model.
 */
export function findByVersion(models: ModelVersion[] | undefined, version: string, production: boolean): ModelRef | undefined {
  return models?.find((v) => v.model.version === String(version) && (v.model.kind === "champion") === production)?.model;
}
