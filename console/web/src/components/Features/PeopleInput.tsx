/**
 * People's input to the improvement loop: reject a feature (the harness fails any candidate that uses it; the planner
 * is told why) or restore it, and pin hypotheses for the planner of every next cycle. Stored where agents cannot
 * change them.
 */
import { useState } from "react";
import { ApiError } from "../../api/client";
import { useFeatureDecision, useHypotheses, usePinHypothesis, useStatus, useUnpinHypothesis } from "../../api/hooks";
import type { ActionResult, FeatureRow } from "../../api/types";
import { ActionButton, ActionDialog } from "../Operate/actions";
import { ACTIONS_DISABLED } from "../Operate/constants";
import { Banner, Card, Pill, Section, TimeAgo } from "../ui";

type Outcome = { tone: "good" | "warn" | "crit"; message: string } | null;

function useActionsBlock(): string | null {
  const status = useStatus();
  const enabled = status.data?.actions_enabled;
  return enabled ? null : enabled === undefined ? "Checking whether actions are enabled on this console." : ACTIONS_DISABLED;
}

const handlers = (set: (o: Outcome) => void, close: () => void) => ({
  onSuccess: (r: ActionResult) => {
    set({ tone: r.ok ? "good" : "warn", message: r.message });
    close();
  },
  onError: (e: Error) => {
    set({ tone: "crit", message: e instanceof ApiError ? e.detail : e.message });
    close();
  },
});

export function FeatureDecision({ f }: { f: FeatureRow }) {
  const block = useActionsBlock();
  const decide = useFeatureDecision();
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const rejecting = !f.rejected;
  return (
    <span className="stack" style={{ gap: 4 }}>
      {f.rejected && (
        <span className="xs" title={`${f.rejected.reason} (${f.rejected.by})`}>
          <Pill tone="crit">rejected by {f.rejected.by}</Pill>
        </span>
      )}
      <ActionButton small disabledReason={block} onClick={() => setOpen(true)}>
        {rejecting ? "Reject…" : "Restore…"}
      </ActionButton>
      {outcome && <span className="xs muted" role="status">{outcome.message}</span>}
      {open && (
        <ActionDialog
          open
          danger={rejecting}
          title={rejecting ? `Reject ${f.name}?` : `Restore ${f.name}?`}
          confirmLabel={rejecting ? "Reject" : "Restore"}
          requireText={{ label: "Reason for the record (at least 10 characters)", minLength: 10 }}
          busy={decide.isPending}
          onCancel={() => setOpen(false)}
          onConfirm={(reason) => decide.mutate({ name: f.name, decision: rejecting ? "reject" : "restore", reason }, handlers(setOutcome, () => setOpen(false)))}
        >
          <p style={{ margin: 0 }}>
            {rejecting
              ? "Any candidate that uses this feature then fails validation, and the planner is told your reason. Models already promoted are not changed."
              : "Candidates may use this feature again."}
          </p>
        </ActionDialog>
      )}
    </span>
  );
}

export function HypothesesSection() {
  const q = useHypotheses();
  const pin = usePinHypothesis();
  const unpin = useUnpinHypothesis();
  const block = useActionsBlock();
  const [text, setText] = useState("");
  const [outcome, setOutcome] = useState<Outcome>(null);
  const rows = q.data ?? [];
  return (
    <Section title="Pinned hypotheses" note="Ideas a person wants tried. The planner sees every pinned hypothesis at the start of each cycle until it is unpinned.">
      <div className="stack">
        {outcome && <Banner tone={outcome.tone}>{outcome.message}</Banner>}
        <Card>
          {rows.length === 0 ? (
            <p className="small muted" style={{ marginTop: 0 }}>Nothing is pinned.</p>
          ) : (
            <ul className="plain small">
              {rows.map((h) => (
                <li key={h.hypothesis_id} className="row" style={{ gap: 8, marginBottom: 6, alignItems: "baseline" }}>
                  <span style={{ flex: 1 }}>{h.text}</span>
                  <span className="xs muted">
                    {h.by}, <TimeAgo iso={h.at} />
                  </span>
                  <ActionButton small disabledReason={block} onClick={() => unpin.mutate({ hypothesis_id: h.hypothesis_id }, handlers(setOutcome, () => undefined))}>
                    Unpin
                  </ActionButton>
                </li>
              ))}
            </ul>
          )}
          <form
            className="row"
            style={{ gap: 8 }}
            onSubmit={(e) => {
              e.preventDefault();
              pin.mutate({ text }, handlers(setOutcome, () => setText("")));
            }}
          >
            <label className="field" style={{ flex: 1, margin: 0 }}>
              <span className="xs muted">New hypothesis (10 to 500 characters)</span>
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="for example: income volatility matters more for thin files" />
            </label>
            <ActionButton variant="primary" disabledReason={block ?? (text.trim().length < 10 ? "Write at least 10 characters." : null)} onClick={() => pin.mutate({ text }, handlers(setOutcome, () => setText("")))}>
              Pin
            </ActionButton>
          </form>
        </Card>
      </div>
    </Section>
  );
}
