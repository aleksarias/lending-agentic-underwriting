/**
 * One hook per endpoint (see docs/console/contract.md). Pages use ONLY these hooks for data.
 * Live screens poll; everything else is cached for 30 s and refetched on focus.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, seg } from "./client";
import type * as T from "./types";

const LIVE = 5_000;
const STATUS = 15_000;

type Params = Record<string, string | number | boolean | null | undefined>;
function useQ<R>(key: unknown[], path: string, params?: Params, refetchInterval?: number, enabled = true) {
  return useQuery<R>({ queryKey: key, queryFn: () => apiGet<R>(path, params), refetchInterval, enabled });
}

// ------------------------------------------------------------------ global
export const useStatus = () => useQ<T.StatusSummary>(["status"], "/status", undefined, STATUS);
export const useOverview = () => useQ<T.OverviewData>(["overview"], "/overview", undefined, STATUS);
export const useSearch = (term: string) =>
  useQ<T.SearchResult[]>(["search", term], "/search", { q: term }, undefined, term.trim().length >= 2);

// ------------------------------------------------------------------ activity / history
export const useActivity = () => useQ<T.ActivityData>(["activity"], "/activity", undefined, LIVE);
export const useTrace = (cycleId: string | null | undefined, after?: string) =>
  useQ<T.TraceEntry[]>(["trace", cycleId, after], "/activity/trace", { cycle_id: cycleId ?? "", after }, LIVE, !!cycleId);
export const useEvents = (params: { types?: string; definition?: string; before?: string; limit?: number } = {}) =>
  useQ<T.EventsPage>(["events", params], "/events", params);
export const useChanges = (from: string | null, to: string | null) =>
  useQ<T.ChangeSet>(["changes", from, to], "/changes", { from: from ?? "", to: to ?? "" }, undefined, !!from && !!to);
export const useCycles = () => useQ<T.CycleSummary[]>(["cycles"], "/cycles");
export const useCycle = (cycleId: string | undefined) =>
  useQ<T.CycleDetail>(["cycle", cycleId], `/cycles/${seg(cycleId ?? "")}`, undefined, undefined, !!cycleId);
export const useLineage = (name: string | undefined, version: string | undefined) =>
  useQ<T.LineageGraph>(["lineage", name, version], `/lineage/${seg(name ?? "")}/${seg(version ?? "")}`, undefined, undefined, !!name && !!version);

// ------------------------------------------------------------------ progress / definitions / pipeline
export const useProgress = () => useQ<T.ProgressData>(["progress"], "/progress");
export const useDefinitions = () => useQ<T.DefinitionVersion[]>(["definitions"], "/definitions");
export const useDefinition = (version: string | undefined) =>
  useQ<T.DefinitionVersion>(["definition", version], `/definitions/${seg(version ?? "")}`, undefined, undefined, !!version);
export const useSensitivity = () => useQ<T.SensitivityData>(["sensitivity"], "/definitions/sensitivity");
export const usePipeline = (definition?: string) => useQ<T.PipelineData>(["pipeline", definition], "/pipeline", { def: definition });

// ------------------------------------------------------------------ upcoming / models / performance / fairness
export const useUpcoming = () => useQ<T.UpcomingData>(["upcoming"], "/upcoming");
export const useModels = () => useQ<T.ModelVersion[]>(["models"], "/models");
export const useModelCard = (name: string | undefined, version: string | undefined) =>
  useQ<T.ModelCard>(["model", name, version], `/models/${seg(name ?? "")}/${seg(version ?? "")}`, undefined, undefined, !!name && !!version);
export const usePerformance = (definition?: string) =>
  useQ<T.PerformanceData>(["performance", definition], "/performance", { def: definition });
export const useEvaluation = (evalId: string | undefined) =>
  useQ<T.EvaluationDetail>(["evaluation", evalId], `/evaluations/${seg(evalId ?? "")}`, undefined, undefined, !!evalId);
export const useFairness = (definition?: string) => useQ<T.FairnessData>(["fairness", definition], "/fairness", { def: definition });

// ------------------------------------------------------------------ data / features / agents
export const useFeed = () => useQ<T.FeedData>(["feed"], "/feed");
export const useCatalog = (definition?: string) => useQ<T.CatalogData>(["catalog", definition], "/catalog", { def: definition });
export const useVariable = (variable: string | undefined, definition?: string) =>
  useQ<T.CatalogVariable>(["variable", variable, definition], `/catalog/${seg(variable ?? "")}`, { def: definition }, undefined, !!variable);
export const useCashflowCohorts = () => useQ<T.CashflowCohorts>(["cashflow"], "/cashflow/cohorts");
export const useFeatures = () => useQ<T.FeatureRow[]>(["features"], "/features");
export const useAgents = () => useQ<T.AgentInfo[]>(["agents"], "/agents");
export const useReports = (params: { kind?: string; cycle_id?: string; candidate_ref?: string } = {}) =>
  useQ<T.ReportMeta[]>(["reports", params], "/reports", params);
export const useReport = (reportId: string | undefined) =>
  useQ<T.Report>(["report", reportId], `/reports/${seg(reportId ?? "")}`, undefined, undefined, !!reportId);
export const useLessons = () => useQ<T.LessonsData>(["lessons"], "/lessons");

// ------------------------------------------------------------------ approvals / operations / cost / settings
export const useApprovals = () => useQ<T.ApprovalsData>(["approvals"], "/approvals", undefined, STATUS);
export const useEvidence = (candidateRef: string | undefined) =>
  useQ<T.EvidencePacket>(["evidence", candidateRef], `/approvals/${seg(candidateRef ?? "")}`, undefined, undefined, !!candidateRef);
export const useDecisions = () => useQ<T.DecisionsData>(["decisions"], "/decisions");
export const useRollouts = () => useQ<T.RolloutsData>(["rollouts"], "/rollouts");
export const useShadow = () => useQ<T.ShadowData>(["shadow"], "/shadow");
export const useAlerts = () => useQ<T.AlertsData>(["alerts"], "/alerts", undefined, STATUS);
export const useCost = () => useQ<T.CostData>(["cost"], "/cost");
export const useSettings = () => useQ<T.SettingsData>(["settings"], "/settings");

// ------------------------------------------------------------------ actions (require LAU_CONSOLE_ACTIONS=1 on the server)
function useAction<V>(fn: (v: V) => Promise<T.ActionResult>, invalidate: unknown[][]) {
  const qc = useQueryClient();
  return useMutation<T.ActionResult, Error, V>({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k })),
  });
}
export const useStopCycle = () =>
  useAction((v: { cycle_id: string; reason: string }) => apiPost<T.ActionResult>("/activity/stop", v), [["activity"], ["status"]]);
export const useRunGate = () =>
  useAction((v: { candidate_ref: string }) => apiPost<T.ActionResult>(`/approvals/${seg(v.candidate_ref)}/gate`), [["evidence"], ["approvals"], ["status"]]);
export const useDecide = () =>
  useAction(
    (v: { candidate_ref: string; decision: "approve" | "reject"; rationale: string }) =>
      apiPost<T.ActionResult>(`/approvals/${seg(v.candidate_ref)}/decision`, { decision: v.decision, rationale: v.rationale }),
    [["evidence"], ["approvals"], ["status"]],
  );
export const usePromote = () =>
  useAction((v: { candidate_ref: string }) => apiPost<T.ActionResult>(`/approvals/${seg(v.candidate_ref)}/promote`), [["evidence"], ["approvals"], ["models"], ["status"], ["rollouts"]]);
export const useAckAlert = () =>
  useAction((v: { alert_id: string; note: string }) => apiPost<T.ActionResult>(`/alerts/${seg(v.alert_id)}/ack`, { note: v.note }), [["alerts"], ["status"]]);
export const useAsk = () =>
  useMutation<T.AskResponse, Error, { question: string }>({ mutationFn: (v) => apiPost<T.AskResponse>("/ask", v) });
