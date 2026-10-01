/**
 * A proposed definition change: config/default_definition.yaml differs from the active definition. Shows what changes,
 * what rebuilds, who has approved this exact hash, and lets a person approve it (two-person rule where configured).
 * Approving changes nothing by itself: the daily job's definition sync applies it once enough people approved.
 */
import { useState } from "react";
import { ApiError } from "../../api/client";
import { useApproveDefinition, useDefinitionProposal, useStatus } from "../../api/hooks";
import type { ActionResult } from "../../api/types";
import { ActionButton, ActionDialog } from "../Operate/actions";
import { ACTIONS_DISABLED } from "../Operate/constants";
import { Banner, Card, KeyValue, Section } from "../ui";

const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function ProposalSection() {
  const q = useDefinitionProposal();
  const status = useStatus();
  const approve = useApproveDefinition();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<{ tone: "good" | "warn" | "crit"; message: string } | null>(null);
  const p = q.data?.proposal;
  if (!p) return null;
  const user = status.data?.user ?? null;
  const enabled = status.data?.actions_enabled;
  const block = !enabled
    ? enabled === undefined
      ? "Checking whether actions are enabled on this console."
      : ACTIONS_DISABLED
    : user && p.approvers.includes(user)
      ? `You (${user}) already approved this hash.`
      : null;
  return (
    <Section title="Proposed change" note="config/default_definition.yaml differs from the active definition. Every label, model and metric depends on the definition, so a change needs approval.">
      <div className="stack">
        {outcome && (
          <Banner tone={outcome.tone} title={outcome.tone === "crit" ? "The approval did not complete" : "Recorded"}>
            {outcome.message}
          </Banner>
        )}
        <Card>
          <p style={{ marginTop: 0 }}>
            <strong>{p.summary}</strong> <span className="mono xs muted">{p.short}</span>
          </p>
          <p className="small">{p.plain_language}</p>
          <KeyValue
            items={[
              ...p.diff.map((d): [string, string] => [d.field, `${show(d.before)} → ${show(d.after)}`]),
              ["Approvals", `${p.approvers.length} of ${p.required}${p.approvers.length ? ` (${p.approvers.join(", ")})` : ""}`],
              ["Rebuilds when applied", p.rebuilds.map((r) => r.stage).join(", ")],
            ]}
          />
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <ActionButton variant="primary" disabledReason={block} onClick={() => setOpen(true)}>
              Approve this hash
            </ActionButton>
            <span className="xs muted">The new definition gets its own holdout budget; champions of the old one keep serving until a new champion is approved.</span>
          </div>
        </Card>
      </div>
      {open && (
        <ActionDialog
          open
          title={`Approve definition ${p.short}?`}
          confirmLabel="Approve"
          requireText={{ label: "What you checked (at least 10 characters)", minLength: 10 }}
          busy={approve.isPending}
          onCancel={() => setOpen(false)}
          onConfirm={(note) =>
            approve.mutate(
              { version: p.version, note },
              {
                onSuccess: (r: ActionResult) => {
                  setOutcome({ tone: r.ok ? "good" : "warn", message: r.message });
                  setOpen(false);
                },
                onError: (e: Error) => {
                  setOutcome({ tone: "crit", message: e instanceof ApiError ? e.detail : e.message });
                  setOpen(false);
                },
              },
            )
          }
        >
          <p style={{ margin: 0 }}>
            Records {user ? `your (${user})` : "your"} approval of this exact hash. It needs {p.required} different approver{p.required === 1 ? "" : "s"}; the daily job applies it
            afterwards and every stage listed rebuilds.
          </p>
        </ActionDialog>
      )}
    </Section>
  );
}
