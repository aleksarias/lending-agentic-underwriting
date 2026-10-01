/** Route table + navigation metadata. Page components are lazy-loaded (charts are heavy). */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

type PageComponent = LazyExoticComponent<ComponentType>;

export interface RouteDef {
  path: string;
  component: PageComponent;
}

export interface NavItem {
  path: string;
  label: string;
  /** optional status count shown in the nav (e.g. approvals waiting) */
  countKey?: "decisions_waiting" | "alerts_open";
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

const P = {
  Overview: lazy(() => import("./pages/Overview")),
  Activity: lazy(() => import("./pages/Activity")),
  Decisions: lazy(() => import("./pages/Decisions")),
  DecisionDetail: lazy(() => import("./pages/DecisionDetail")),
  Progress: lazy(() => import("./pages/Progress")),
  History: lazy(() => import("./pages/History")),
  CycleDetail: lazy(() => import("./pages/CycleDetail")),
  Compare: lazy(() => import("./pages/Compare")),
  Definitions: lazy(() => import("./pages/Definitions")),
  DefinitionDetail: lazy(() => import("./pages/DefinitionDetail")),
  Upcoming: lazy(() => import("./pages/Upcoming")),
  Models: lazy(() => import("./pages/Models")),
  ModelDetail: lazy(() => import("./pages/ModelDetail")),
  Performance: lazy(() => import("./pages/Performance")),
  EvaluationDetail: lazy(() => import("./pages/EvaluationDetail")),
  Fairness: lazy(() => import("./pages/Fairness")),
  Feed: lazy(() => import("./pages/Feed")),
  Data: lazy(() => import("./pages/Data")),
  VariableDetail: lazy(() => import("./pages/VariableDetail")),
  Features: lazy(() => import("./pages/Features")),
  Agents: lazy(() => import("./pages/Agents")),
  ReportDetail: lazy(() => import("./pages/ReportDetail")),
  Lessons: lazy(() => import("./pages/Lessons")),
  Approvals: lazy(() => import("./pages/Approvals")),
  ApprovalDetail: lazy(() => import("./pages/ApprovalDetail")),
  Rollouts: lazy(() => import("./pages/Rollouts")),
  Readiness: lazy(() => import("./pages/Readiness")),
  Shadow: lazy(() => import("./pages/Shadow")),
  Alerts: lazy(() => import("./pages/Alerts")),
  Cost: lazy(() => import("./pages/Cost")),
  Settings: lazy(() => import("./pages/Settings")),
  NotFound: lazy(() => import("./pages/NotFound")),
};

export const ROUTES: RouteDef[] = [
  { path: "/", component: P.Overview },
  { path: "/activity", component: P.Activity },
  { path: "/decisions", component: P.Decisions },
  { path: "/decisions/:decisionId", component: P.DecisionDetail },
  { path: "/progress", component: P.Progress },
  { path: "/history", component: P.History },
  { path: "/history/cycles/:cycleId", component: P.CycleDetail },
  { path: "/history/compare", component: P.Compare },
  { path: "/definitions", component: P.Definitions },
  { path: "/definitions/:version", component: P.DefinitionDetail },
  { path: "/upcoming", component: P.Upcoming },
  { path: "/models", component: P.Models },
  { path: "/models/:name/:version", component: P.ModelDetail },
  { path: "/performance", component: P.Performance },
  { path: "/performance/evaluations/:evalId", component: P.EvaluationDetail },
  { path: "/fairness", component: P.Fairness },
  { path: "/feed", component: P.Feed },
  { path: "/data", component: P.Data },
  { path: "/data/:variable", component: P.VariableDetail },
  { path: "/features", component: P.Features },
  { path: "/agents", component: P.Agents },
  { path: "/agents/reports/:reportId", component: P.ReportDetail },
  { path: "/agents/lessons", component: P.Lessons },
  { path: "/approvals", component: P.Approvals },
  { path: "/approvals/:candidateRef", component: P.ApprovalDetail },
  { path: "/rollouts", component: P.Rollouts },
  { path: "/readiness", component: P.Readiness },
  { path: "/shadow", component: P.Shadow },
  { path: "/alerts", component: P.Alerts },
  { path: "/cost", component: P.Cost },
  { path: "/settings", component: P.Settings },
  { path: "*", component: P.NotFound },
];

export const NAV: NavGroup[] = [
  { label: "Now", items: [
    { path: "/", label: "Overview" },
    { path: "/activity", label: "Live activity" },
    { path: "/decisions", label: "Decisions" },
  ] },
  { label: "Over time", items: [
    { path: "/progress", label: "Progress" },
    { path: "/history", label: "History" },
    { path: "/definitions", label: "Definitions" },
  ] },
  { label: "Next", items: [{ path: "/upcoming", label: "Upcoming" }] },
  { label: "Models and evidence", items: [
    { path: "/models", label: "Models" },
    { path: "/performance", label: "Performance" },
    { path: "/fairness", label: "Fairness & compliance" },
  ] },
  { label: "Data and feedback", items: [
    { path: "/feed", label: "Loan status feed" },
    { path: "/data", label: "Data catalog" },
    { path: "/features", label: "Features lab" },
  ] },
  { label: "Agents", items: [{ path: "/agents", label: "Agents" }] },
  { label: "Decide and operate", items: [
    { path: "/approvals", label: "Approvals", countKey: "decisions_waiting" },
    { path: "/rollouts", label: "Rollouts" },
    { path: "/readiness", label: "Readiness" },
    { path: "/shadow", label: "Shadow scoring" },
    { path: "/alerts", label: "Alerts", countKey: "alerts_open" },
    { path: "/cost", label: "Cost" },
    { path: "/settings", label: "Settings" },
  ] },
];
