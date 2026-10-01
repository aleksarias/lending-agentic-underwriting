/**
 * Settings content. Everything here is read-only: configuration lives in git and changes through the command line, and
 * every change is versioned. Access checks come first because they say whether agent isolation is proven.
 */
import "./settings.css";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import type { SettingsData, Tile } from "../../api/types";
import { fmtAgo, fmtDateTime } from "../../lib/format";
import { Banner, PageHeader, Section, Tiles, UnavailableState } from "../ui";
import { AccessChecks, BenchmarkDefinitions, ConfigVersions, ReportsSection, accessFacts, isDirty } from "./AccessAndVersions";
import { ConfigBlock } from "./ConfigTables";

const TOC: [string, string][] = [
  ["settings-access", "Access checks"],
  ["settings-thresholds", "Thresholds"],
  ["settings-budgets", "Budgets"],
  ["settings-models", "Models"],
  ["settings-protected", "Protected classes"],
  ["settings-benchmarks", "Benchmarks"],
  ["settings-versions", "Versions"],
  ["settings-notifications", "Notifications"],
  ["settings-reports", "Reports"],
];

function sentence(s: SettingsData): string {
  const a = accessFacts(s.access_checks);
  const dirty = s.config_versions.some(isDirty);
  const access = a.total
    ? `${a.passed} of ${a.total} access checks passed ${fmtAgo(a.last)}${a.failed.length ? `, so isolation is not proven for ${a.failed.length}` : ""}`
    : "no access checks have been recorded, so isolation is not proven";
  return `Nothing here can be edited from the console: ${access}, and ${s.config_versions.length} components are versioned${dirty ? ", with uncommitted changes in the code" : ""}.`;
}

export function SettingsView({ s }: { s: SettingsData }) {
  const loc = useLocation();
  // a link such as /settings#settings-access scrolls once the content exists (the router does not do it for us)
  useEffect(() => {
    if (loc.hash) document.getElementById(loc.hash.slice(1))?.scrollIntoView();
  }, [loc.hash]);

  const a = accessFacts(s.access_checks);
  const newest = s.config_versions.map((v) => v.recorded_at).sort().pop() ?? null;
  const code = s.config_versions.find((v) => v.component === "code");
  const tiles: Tile[] = [
    {
      key: "access",
      label: "Access checks",
      value: a.total ? `${a.passed} of ${a.total} passed` : "Not run",
      sub: a.last ? `run ${fmtAgo(a.last)}` : "run lau check-access",
      tone: a.total === 0 ? "warn" : a.failed.length ? "crit" : "good",
    },
    { key: "versions", label: "Versioned components", value: String(s.config_versions.length), sub: newest ? `newest recorded ${fmtAgo(newest)}` : "none recorded" },
    {
      key: "code",
      label: "Code version",
      value: code ? (isDirty(code) ? "Uncommitted changes" : "Matches a commit") : "Not recorded",
      sub: code?.git_sha ? `commit ${code.git_sha.slice(0, 10)}` : null,
      tone: code && isDirty(code) ? "warn" : null,
    },
    { key: "notify", label: "Notifications", value: "Not configured", sub: "email or Slack" },
  ];

  return (
    <>
      <PageHeader eyebrow="Decide and operate" title="Reports and settings" summary={sentence(s)} />
      <Banner tone="neutral" title="Changes go through git and the command line, and every change is versioned">
        <span className="small">
          Thresholds, budgets, models, protected classes and benchmarks are YAML files in the repository: edit, review and merge them there. The definition of default changes with{" "}
          <code>lau default-definition plan</code> and <code>apply</code>. Each change is recorded as a new version (hash, time and git commit) when a cycle starts, a definition is
          applied or <code>lau versions record</code> runs, so any past state can be reconstructed.
        </span>
      </Banner>
      <Tiles tiles={tiles} />
      <nav aria-label="On this page" className="settings-toc small">
        {TOC.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </nav>

      <Section
        id="settings-access"
        title="Access checks"
        note={
          <>
            Each row is a probe run by <code>lau check-access</code>: an identity tries to read an object that it may, or must not, read. If a probe fails, isolation between that identity and that object is not proven.
            {a.last && <> The latest run was {fmtDateTime(a.last)}.</>}
          </>
        }
      >
        <AccessChecks checks={s.access_checks} />
      </Section>

      <ConfigBlock
        id="settings-thresholds"
        title="Thresholds"
        note="Limits the harness, the fairness checks and monitoring apply. Changing one means changing a file in git: it is reviewed there and recorded as a new version."
        root="thresholds"
        data={s.thresholds}
      />
      <ConfigBlock
        id="settings-budgets"
        title="Budgets"
        note="Hard caps. The orchestrator enforces them; agents cannot change them."
        root="budgets"
        data={s.budgets}
      />
      <ConfigBlock id="settings-models" title="Models" note="Which Claude model runs each agent role." root="models" data={s.models} />
      <ConfigBlock
        id="settings-protected"
        title="Protected classes and prohibited features"
        note="Used by the fairness checks and the proxy scan. No model may use a prohibited feature."
        root="protected_classes"
        data={s.protected_classes}
      />

      <Section
        id="settings-benchmarks"
        title="Benchmark definitions"
        note="Every model is re-scored under each of these on the same loans. They are frozen: new ones can be added and existing ones are never edited."
      >
        <BenchmarkDefinitions rows={s.benchmarks} />
      </Section>

      <Section
        id="settings-versions"
        title="Config versions"
        note="The latest recorded version of everything that shapes a cycle. The table behind it is a change log: a row is added only when a component's hash changes."
      >
        <ConfigVersions rows={s.config_versions} />
      </Section>

      <Section id="settings-notifications" title="Notifications">
        <UnavailableState u={s.notifications} title="Notifications are not configured" />
      </Section>

      <Section id="settings-reports" title="Reports">
        <ReportsSection />
      </Section>
    </>
  );
}
