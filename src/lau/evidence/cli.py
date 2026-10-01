"""`lau evidence ...` sub-app: refresh the aggregate tables the Underwriting Console reads.

Mount with `app.add_typer(lau.evidence.cli.app, name="evidence")`. Everything runs as the harness identity.
"""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Evidence backend: benchmark ledger, sensitivity, vintages, cash-flow cohorts, proxy scan, verdict.",
)
console = Console()


def _log(msg: str) -> None:
    console.print(msg, markup=False, highlight=False)


def _run(only: str | None) -> None:
    from lau.credentials import CredentialsMissingError
    from lau.evidence.run import EvidenceRunError, run_all

    try:
        counts = run_all(log=_log, only=only)
    except CredentialsMissingError as e:
        _log(f"error: {e}")
        raise typer.Exit(1) from e
    except ValueError as e:  # unknown --only step
        raise typer.BadParameter(str(e)) from e
    except EvidenceRunError as e:
        _log(f"error: {len(e.errors)} step(s) failed; written so far: {e.counts}")
        raise typer.Exit(1) from e
    _log("done: " + ", ".join(f"{t}={n}" for t, n in counts.items()))


@app.command("run")
def run(
    only: str = typer.Option(
        None,
        "--only",
        help="Comma-separated steps (table names or aliases: registry, metrics, benchmark, sensitivity, vintage, "
        "cashflow, proxies, verdict). Default: all, in dependency order.",
    ),
) -> None:
    """Recompute the evidence tables (benchmarks, sensitivity, vintages, cohorts, proxies, verdict, registry)."""
    _run(only)


@app.command("sync-registry")
def sync_registry() -> None:
    """Replace ops.model_registry with the current MLflow / Unity Catalog registry."""
    _run("model_registry")


@app.command("flatten-metrics")
def flatten_metrics() -> None:
    """Replace ops.evaluation_metrics with the flattened numbers of every ops.evaluations result."""
    _run("evaluation_metrics")
