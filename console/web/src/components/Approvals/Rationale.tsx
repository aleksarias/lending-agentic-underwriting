/**
 * The rationale of a recorded decision. A promotion rationale is a person's own words. A definition rationale is the
 * plan text that was approved (a multi-line listing of changes and pipeline stages), so it gets a one-line summary
 * and the full text behind a toggle.
 */
import { useId, useState } from "react";
import "./Approvals.css";

/** The API keeps only this many characters of an approved plan (services/evals.py, definition_approval_records). */
const PLAN_LIMIT = 600;

/** One line for a definition plan, or null when the text is not a recognizable plan. */
export function planSummary(text: string): string | null {
  if (!/^\s*Definition in YAML/.test(text)) return null;
  const changes = text.match(/Changes:\s*\n([\s\S]*?)\n\s*Stages:/);
  if (changes) {
    const lines = changes[1].split("\n").map((s) => s.trim()).filter(Boolean);
    if (lines.length) return `Changes: ${lines.join("; ")}`;
  }
  if (/Definition unchanged\./.test(text)) return "Definition unchanged. The approved plan rebuilds the pipeline stages marked REBUILD.";
  return null;
}

export function Rationale({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const clean = (text ?? "").trim();
  if (!clean) return <span className="faint">none recorded</span>;
  const summary = planSummary(clean);
  if (summary) {
    return (
      <div className="approvals-rationale">
        <div className="approvals-rationale-text open">{summary}</div>
        <button type="button" className="approvals-more" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {open ? "Hide the approved plan" : "Show the approved plan"}
        </button>
        {open && (
          <>
            <pre id={id} className="approvals-raw">
              {clean}
            </pre>
            {clean.length >= PLAN_LIMIT && <span className="xs muted">This is the start of the plan: the API returns at most {PLAN_LIMIT} characters of it.</span>}
          </>
        )}
      </div>
    );
  }
  const long = clean.length > 140 || clean.split("\n").length > 2;
  return (
    <div className="approvals-rationale">
      <div id={id} className={`approvals-rationale-text ${open || !long ? "open" : ""}`}>
        {clean}
      </div>
      {long && (
        <button type="button" className="approvals-more" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}
