"""Console API: GET /api/decisions (screen 3). The real-time decision API is not deployed yet, so `live` is an
Unavailable payload and `preview` documents the response the endpoint will return.

Contract: docs/console/contract.md and console/web/src/api/types.ts.
"""

from __future__ import annotations

from lau.console.services import definitions as defs
from lau.console.util import api_router, unavailable

router = api_router()

REQUIRES = [
    "Model Serving endpoint for the champion (serving alias)",
    "Online feature store (Lakebase) with decision-time features",
    "Decision log table (ops.decisions) written by the endpoint",
    "Adverse-action reason-code service",
]


@router.get("/decisions")
def decisions() -> dict:
    active = defs.active_version()
    return {
        "live": unavailable(
            "No application is decided by a model yet: the real-time decision API has not been deployed. "
            "Until it is, decisions, latency and fallbacks cannot be shown.",
            REQUIRES,
        ),
        "preview": {
            "endpoint": "POST /v1/decisions",
            "policy_version": active,
            "example_response": {
                "application_id": "APP-000123",
                "decision": "approve",
                "pd": 0.0412,
                "cutoff_pd": 0.0835,
                "model": {"name": "pd_model", "version": "3", "alias": "serving"},
                "definition_version": active,
                "reason_codes": [
                    {"rank": 1, "feature": "bureau_score", "text": "Credit score below the approved range"},
                    {"rank": 2, "feature": "pmt_to_income", "text": "Payment is a high share of income"},
                ],
                "fallback": False,
                "latency_ms": 38,
            },
        },
    }
