/** Pass/fail checks as pills with the plain-language meaning of each, failures first. Status is always in the text. */
import { Pill } from "../ui";
import { checkDetail, checkName } from "./checks";
import "./ApprovalDetail.css";

export function checkCounts(checks: Record<string, boolean>): { passed: number; total: number } {
  const values = Object.values(checks);
  return { passed: values.filter(Boolean).length, total: values.length };
}

export function CheckList({ checks }: { checks: Record<string, boolean> }) {
  // Array.prototype.sort is stable, so checks keep the harness order within passed and within failed
  const entries = Object.entries(checks).sort(([, a], [, b]) => Number(a) - Number(b));
  return (
    <ul className="approvaldetail-checks">
      {entries.map(([key, ok]) => (
        <li key={key}>
          <span className="what">
            <strong className="small">{checkName(key)}</strong>
            {checkDetail(key) && <span className="detail">{checkDetail(key)}</span>}
          </span>
          <Pill tone={ok ? "good" : "crit"}>{ok ? "Passed" : "Failed"}</Pill>
        </li>
      ))}
    </ul>
  );
}
