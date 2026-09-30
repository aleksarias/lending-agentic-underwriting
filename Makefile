.PHONY: install test test-integration lint fmt secrets init plan apply cycle status deploy teardown demo

install:            ## dev environment (uv) + pre-commit hooks
	uv sync
	uv run pre-commit install

test:               ## offline unit tests (local DuckDB lake, no network)
	uv run pytest -q

test-integration:   ## tests that hit the Databricks workspace (needs `lau init`)
	uv run pytest -q -m integration

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

secrets:            ## scan working tree and history for secrets
	gitleaks detect --source . --config .gitleaks.toml --no-banner --redact
	gitleaks protect --staged --config .gitleaks.toml --no-banner --redact

init:
	uv run lau init

plan:
	uv run lau default-definition plan

apply:
	uv run lau default-definition apply

cycle:
	uv run lau run-cycle

status:
	uv run lau status

# The Databricks CLI gets ONLY the admin host/credential from .env (never the SP secrets or Anthropic key).
DBX_ENV = env -i PATH="$$PATH" HOME="$$HOME" $$(grep -E '^(DATABRICKS_HOST|DATABRICKS_TOKEN|DATABRICKS_CONFIG_PROFILE)=' .env | grep -v '=$$' | xargs)

deploy:             ## deploy PAUSED jobs (needs harness SP id from .lau/workspace_state.json)
	$(DBX_ENV) databricks bundle deploy -t dev --var="harness_sp=$$(python3 -c 'import json;print(json.load(open(".lau/workspace_state.json"))["service_principals"]["harness"]["application_id"])')"

teardown:           ## remove EVERYTHING the project created (jobs, catalog/schemas, SPs, experiment; restores adopted warehouse)
	-$(DBX_ENV) databricks bundle destroy -t dev --auto-approve
	uv run lau teardown

demo:               ## end-to-end synthetic demo (local backend): 90 DPD -> 60 DPD
	uv run python scripts/demo.py
