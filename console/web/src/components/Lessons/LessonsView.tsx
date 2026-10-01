/**
 * Lessons the curator agent wrote, grouped by the definition of default they were learned under. By default the page
 * shows what applies today: lessons learned under the active definition plus definition-independent ones. Filters live
 * in the query string. Every lesson is an agent claim (proposed) and keeps its id.
 */
import { Link } from "react-router-dom";
import type { DefinitionRef, Lesson, LessonsData } from "../../api/types";
import { Banner, Card, EmptyState, KindTag, Pill } from "../ui";
import { ChipFilter, DefBadge, FilterSelect, LinkedText, UrlSearch, useDefinitionRefs, useUrlFilters, type FilterOption } from "../Agents/shared";

const KEYS = ["def", "scope", "status", "q"] as const;
type Filters = Record<(typeof KEYS)[number], string>;

const INDEPENDENT = "definition-independent";

const scopeLabel = (s: string) => (s === INDEPENDENT ? "Definition-independent" : s === "definition-specific" ? "Definition-specific" : s);

function statusLabel(s: string): string {
  if (s === "active") return "Active";
  const m = /^unverified-under-(.+)$/.exec(s);
  return m ? `Unverified under ${m[1]}` : s;
}

const isUnverified = (s: string) => s.startsWith("unverified-under-");

/** Does a lesson pass every filter except `skip` (used to count the options of one filter given the others)? */
function passes(l: Lesson, f: Filters, active: string | null, skip?: keyof Filters): boolean {
  if (skip !== "def") {
    if (f.def === "") {
      if (!(l.definition_version === active || l.scope === INDEPENDENT)) return false;
    } else if (f.def !== "all" && !l.definition_version.startsWith(f.def)) return false;
  }
  if (skip !== "scope" && f.scope && l.scope !== f.scope) return false;
  if (skip !== "status" && f.status && l.status !== f.status) return false;
  if (skip !== "q" && f.q) {
    const q = f.q.trim().toLowerCase();
    if (q && !l.text.toLowerCase().includes(q) && !l.id.toLowerCase().includes(q)) return false;
  }
  return true;
}

export function lessonsSentence(d: LessonsData, active: DefinitionRef | null): string {
  const ls = d.lessons;
  if (!ls.length) return "The curator has not written any lessons yet.";
  const own = ls.filter((l) => l.definition_version === d.active_definition).length;
  const carried = ls.filter((l) => l.definition_version !== d.active_definition && l.scope === INDEPENDENT).length;
  const other = ls.length - own - carried;
  const def = active ? ` (${active.summary})` : "";
  return `${own + carried} of ${ls.length} lessons apply under the active definition${def}: ${own} learned under it and ${carried} definition-independent ${
    carried === 1 ? "one" : "ones"
  } carried forward. ${other} learned under another definition ${other === 1 ? "is" : "are"} unverified and hidden by default.`;
}

function Group({ version, lessons, active, def }: { version: string; lessons: Lesson[]; active: boolean; def: DefinitionRef | null }) {
  return (
    <section className="section" aria-label={`Lessons learned under ${def?.summary ?? version}`}>
      <div className="section-head">
        <h2>{active ? "Learned under the active definition" : "Learned under an earlier definition"}</h2>
        <span className="small muted">
          {lessons.length} lesson{lessons.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="row small muted">
        <DefBadge version={version} />
        <span>
          {active
            ? "These were learned under the definition in force now."
            : "Definition-independent lessons carry forward. Definition-specific ones are unverified under the active definition and must not be relied on until a later cycle confirms them."}
        </span>
      </div>
      <Card flush kind="proposed">
        <ul className="list" style={{ padding: "0 16px" }}>
          {lessons.map((l) => (
            <li key={l.id} id={l.id} className="item stack" style={{ gap: 6 }}>
              <div className="row" style={{ gap: 8 }}>
                <span className="mono">
                  <strong>{l.id}</strong>
                </span>
                <Pill tone={l.scope === INDEPENDENT ? "accent" : "neutral"}>{scopeLabel(l.scope)}</Pill>
                <Pill tone={isUnverified(l.status) ? "warn" : "good"}>{statusLabel(l.status)}</Pill>
                <KindTag kind="proposed" />
              </div>
              <div>
                <LinkedText text={l.text} />
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

export function LessonsView({ data }: { data: LessonsData }) {
  const f = useUrlFilters(KEYS);
  const { find, active, all } = useDefinitionRefs();
  const activeVersion = data.active_definition;
  const lessons = data.lessons;

  const definitionVersions = [...new Set(lessons.map((l) => l.definition_version))];
  const countDef = (fn: (l: Lesson) => boolean) => lessons.filter((l) => passes(l, f.values, activeVersion, "def") && fn(l)).length;
  const defOptions: FilterOption[] = [
    { value: "", label: `Active definition and definition-independent (${countDef((l) => l.definition_version === activeVersion || l.scope === INDEPENDENT)})` },
    { value: "all", label: `All definitions (${countDef(() => true)})` },
    ...definitionVersions.map((v) => ({ value: v, label: `Learned under ${find(v)?.summary ?? v.slice(0, 8)} · ${v.slice(0, 8)} (${countDef((l) => l.definition_version === v)})` })),
  ];

  const scopes = [...new Set(lessons.map((l) => l.scope))];
  const statuses = [...new Set(lessons.map((l) => l.status))].sort((a, b) => (a === "active" ? -1 : b === "active" ? 1 : a.localeCompare(b)));
  const countWhere = (key: keyof Filters, value: string) => lessons.filter((l) => passes(l, f.values, activeVersion, key) && (key === "scope" ? l.scope === value : l.status === value)).length;
  const countAll = (key: keyof Filters) => lessons.filter((l) => passes(l, f.values, activeVersion, key)).length;

  const shown = lessons.filter((l) => passes(l, f.values, activeVersion));
  // lessons that only the definition filter keeps out of view (the default view hides those learned under other definitions)
  const hiddenByDefinition = f.values.def === "all" ? 0 : lessons.filter((l) => passes(l, f.values, activeVersion, "def") && !passes(l, f.values, activeVersion)).length;
  // groups: the active definition first, then the others in the order the definitions are known (newest first)
  const order = [activeVersion, ...all.map((r) => r.version)].filter((v): v is string => !!v);
  const versions = [...new Set(shown.map((l) => l.definition_version))].sort((a, b) => {
    const ia = order.findIndex((o) => o.startsWith(a) || a.startsWith(o));
    const ib = order.findIndex((o) => o.startsWith(b) || b.startsWith(o));
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  return (
    <>
      <Banner tone="neutral" title="Lessons are proposed, not measured">
        <span className="small">
          The curator agent writes lessons after each cycle from what the harness and the other agents reported. The planner is shown the ones that apply to the active definition.
          A lesson flagged unverified was learned under a different definition of default and must not be relied on until a later cycle confirms it. Reports behind them are in the{" "}
          <Link to="/agents">reports library</Link>.
        </span>
      </Banner>

      <Card>
        <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
          <FilterSelect label="Definition" value={f.values.def} onChange={(v) => f.set("def", v)} options={defOptions} />
          <ChipFilter
            label="Scope"
            value={f.values.scope}
            onChange={(v) => f.set("scope", v)}
            options={[{ value: "", label: "All", count: countAll("scope") }, ...scopes.map((s) => ({ value: s, label: scopeLabel(s), count: countWhere("scope", s) }))]}
          />
          <ChipFilter
            label="Status"
            value={f.values.status}
            onChange={(v) => f.set("status", v)}
            options={[{ value: "", label: "All", count: countAll("status") }, ...statuses.map((s) => ({ value: s, label: statusLabel(s), count: countWhere("status", s) }))]}
          />
          <UrlSearch label="Search text or id" value={f.values.q} onChange={(v) => f.set("q", v)} placeholder="for example L-c7d159 or thin-file" />
          {f.active && (
            <button type="button" className="btn small" onClick={f.clear}>
              Reset to default view
            </button>
          )}
        </div>
        <div className="row small muted" style={{ marginTop: 8 }}>
          <span>
            Showing {shown.length} of {lessons.length} lessons.
          </span>
          {hiddenByDefinition > 0 && (
            <button type="button" className="btn small" onClick={() => f.set("def", "all")}>
              Include the {hiddenByDefinition} learned under other definitions
            </button>
          )}
        </div>
      </Card>

      {shown.length === 0 ? (
        <EmptyState
          title={lessons.length ? "No lessons match these filters" : "No lessons yet"}
          action={
            lessons.length ? (
              <button type="button" className="btn small" onClick={f.clear}>
                Reset to default view
              </button>
            ) : undefined
          }
        >
          {lessons.length
            ? "Change a filter, or reset to the default view of the active definition plus definition-independent lessons."
            : "The curator agent adds lessons at the end of every improvement cycle. They appear here with their ids."}
        </EmptyState>
      ) : (
        versions.map((v) => (
          <Group
            key={v}
            version={v}
            lessons={shown.filter((l) => l.definition_version === v)}
            active={!!activeVersion && v === activeVersion}
            def={find(v) ?? (active && active.version.startsWith(v) ? active : null)}
          />
        ))
      )}
    </>
  );
}
