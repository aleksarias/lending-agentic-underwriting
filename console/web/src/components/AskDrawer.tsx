/**
 * "Ask the system": a read-only agent answers plain-language questions from the console's own tables (POST /api/ask).
 *
 * The answer is an agent's claim, so it is shown as proposed, with the SQL it ran and the rows it got back so a person can
 * check it. The drawer is a modal dialog: focus moves into it, stays inside it, Escape and a click on the backdrop close
 * it, and focus returns to what opened it. A question in flight survives closing the drawer (see exchange.ts).
 */
import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useAsk } from "../api/hooks";
import type { AskResponse } from "../api/types";
import { fmtNum, fmtUsd } from "../lib/format";
import { exchangeStore, getDraft, setDraft } from "./AskDrawer/exchange";
import { describeAskError } from "./AskDrawer/errors";
import "./AskDrawer/AskDrawer.css";
import { Markdown } from "./Markdown";
import { Card, CodeBlock, KindTag, Loading, Pill } from "./ui";

const EXAMPLES = [
  "Is the system improving?",
  "Why is v11 not the best known model?",
  "Which features are flagged as proxies?",
  "What did the last improvement cycle cost?",
  "Which alerts are open, and what raised them?",
];
const MIN_LENGTH = 3;
const MAX_LENGTH = 2000;
const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function Answer({ data }: { data: AskResponse }) {
  return (
    <div className="stack" style={{ gap: 12 }}>
      <Card kind="proposed" title="Answer from the agent">
        <div className="row between" style={{ marginBottom: 6 }}>
          <KindTag kind="proposed" />
          <span className="xs muted">An agent wrote this. It is a claim to check against the queries below, not a measurement.</span>
        </div>
        <Markdown source={data.answer} />
      </Card>

      <div className="stack">
        <h3 style={{ fontFamily: "var(--font-body)", fontSize: "var(--fs-md)" }}>
          Queries it ran <span className="muted">({data.queries.length})</span>
        </h3>
        {data.queries.length === 0 ? (
          <div className="row">
            <Pill tone="warn">No queries</Pill>
            <span className="small">The agent answered without reading any table, so nothing here is backed by rows. Treat it with extra caution.</span>
          </div>
        ) : (
          data.queries.map((q, i) => (
            <div key={i} className="ask-query">
              <div className="row between">
                <strong className="small">Query {i + 1}</strong>
                <span className="xs muted">
                  {fmtNum(q.rows)} row{q.rows === 1 ? "" : "s"} returned
                </span>
              </div>
              <CodeBlock>{q.sql}</CodeBlock>
            </div>
          ))
        )}
      </div>

      <div className="xs muted">
        Cost {fmtUsd(data.cost_usd, 4)} · model <span className="mono">{data.model}</span> · recorded against this month's agent spend
      </div>
    </div>
  );
}

export function AskDrawer({ onClose }: { onClose: () => void }) {
  const ask = useAsk();
  const exchange = useSyncExternalStore(exchangeStore.subscribe, exchangeStore.getSnapshot);
  const [text, setText] = useState(getDraft);
  const drawerRef = useRef<HTMLElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const closeRef = useRef(onClose);
  const downOnBackdrop = useRef(false);
  const titleId = useId();
  const helpId = useId();
  const areaId = useId();

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  // modal behavior: focus in, keep focus in, Escape closes, focus back to the opener
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    areaRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      const drawer = drawerRef.current;
      if (e.key === "Escape") {
        // a confirmation dialog on top of the drawer would handle its own Escape; none is opened from here
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !drawer) return;
      const items = Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
        e.preventDefault();
        first.focus();
      }
    };
    const onFocusIn = (e: FocusEvent) => {
      if (drawerRef.current && e.target instanceof Node && !drawerRef.current.contains(e.target)) areaRef.current?.focus();
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("focusin", onFocusIn);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  const pending = exchange.status === "pending";
  const trimmed = text.trim();
  const canSubmit = trimmed.length >= MIN_LENGTH && !pending;

  const submit = useCallback(() => {
    const question = text.trim();
    if (question.length < MIN_LENGTH || exchangeStore.getSnapshot().status === "pending") return;
    const id = exchangeStore.begin(question);
    // the result is written to the store even if the drawer is closed before it arrives
    ask.mutateAsync({ question }).then(
      (data) => exchangeStore.resolve(id, data),
      (error) => exchangeStore.reject(id, error),
    );
  }, [ask, text]);

  const onTextKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  };

  const change = (value: string) => {
    setText(value);
    setDraft(value);
  };

  const problem = exchange.status === "error" ? describeAskError(exchange.error) : null;

  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        downOnBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        // closes only when the press and the release were both on the backdrop, so selecting text and letting go outside does not close it
        if (downOnBackdrop.current && e.target === e.currentTarget) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <aside ref={drawerRef} className="drawer ask-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={helpId}>
        <div className="ask-head">
          <div>
            <h2 id={titleId}>Ask the system</h2>
            <p id={helpId} className="small muted">
              A read-only agent answers from the console's tables and shows the queries it ran. It cannot change anything or approve anything.
            </p>
          </div>
          <button className="btn small" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label className="field" htmlFor={areaId}>
            Your question
            <textarea
              id={areaId}
              ref={areaRef}
              value={text}
              maxLength={MAX_LENGTH}
              rows={3}
              placeholder="For example: Is the system improving?"
              onChange={(e) => change(e.target.value)}
              onKeyDown={onTextKey}
            />
          </label>
          <div className="row between">
            <span className="xs muted">
              {trimmed.length > 0 && trimmed.length < MIN_LENGTH ? `At least ${MIN_LENGTH} characters. ` : ""}
              {text.length >= MAX_LENGTH - 200 ? `${fmtNum(text.length)} of ${fmtNum(MAX_LENGTH)} characters. ` : ""}
              Ctrl or Cmd with Enter sends it.
            </span>
            <button className="btn primary" type="submit" disabled={!canSubmit}>
              {pending ? "Asking…" : "Ask"}
            </button>
          </div>
        </form>

        <div className="stack" style={{ gap: 6 }}>
          <span className="xs muted">Examples</span>
          <div className="ask-examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="ask-chip"
                disabled={pending}
                onClick={() => {
                  change(ex);
                  areaRef.current?.focus();
                }}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        <div aria-live="polite" className="stack" style={{ gap: 12 }}>
          {exchange.status !== "idle" && <blockquote className="ask-asked">You asked: {exchange.question}</blockquote>}

          {pending && (
            <div className="stack" style={{ gap: 6 }}>
              <Loading label="The agent is reading the tables" height={96} />
              <span className="small muted">
                The agent is reading the tables and writing SQL. This can take a minute. Questions run one at a time, and you can close this drawer: the answer will be here when you
                open it again.
              </span>
            </div>
          )}

          {problem && (
            <div className="ask-problem" role="alert">
              <div className="title">{problem.title}</div>
              <div className="small">{problem.body}</div>
              {problem.detail && <div className="xs muted">Console message: {problem.detail}</div>}
              {problem.link && (
                <Link className="small" to={problem.link.to} onClick={onClose}>
                  {problem.link.label}
                </Link>
              )}
            </div>
          )}

          {exchange.status === "done" && exchange.data && <Answer data={exchange.data} />}
        </div>
      </aside>
    </div>
  );
}
