"""Two-person rule: how many different people must approve a promotion or a definition change.

Configured per environment in config/thresholds.yaml (`approvals.<kind>.<environment>`); defaults to 1. Approvals are
counted per distinct approver, a rejection by anyone blocks, and one person cannot approve the same thing twice.
"""

from __future__ import annotations

from collections.abc import Iterable

from lau.settings import get_settings


class ApprovalError(ValueError):
    pass


def required(kind: str) -> int:
    s = get_settings()
    cfg = (s.thresholds.get("approvals") or {}).get(kind) or {}
    return max(1, int(cfg.get(s.project.environment, 1)))


def tally(rows: Iterable[dict], approver_key: str = "approver", decision_key: str | None = "decision") -> dict:
    """{approvers: [...distinct approvers who approved], rejected_by: [...], count: n} from approval rows."""
    approvers: list[str] = []
    rejected: list[str] = []
    for r in rows:
        who = str(r.get(approver_key) or "")
        decision = "approve" if decision_key is None else str(r.get(decision_key) or "")
        if decision == "reject" and who not in rejected:
            rejected.append(who)
        elif decision == "approve" and who not in approvers:
            approvers.append(who)
    return {"approvers": approvers, "rejected_by": rejected, "count": len(approvers)}
