"""Hits the live workspace (run with `make test-integration` after `lau init` + one `apply`).

Proves isolation is enforced by Unity Catalog itself: queries go through `DatabricksStore._query`, which bypasses
the in-process ACL, so only platform grants decide.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

DENY = [("holdout", "oot_labels"), ("labels", "labels_all"), ("raw", "protected_attributes"),
        ("raw", "performance"), ("curated", "applications"), ("ops", "pipeline_state"), ("ops", "active_definition")]
ALLOW = [("labels", "labels_active"), ("curated", "applications_dev"), ("curated", "data_catalog")]
DENIED_CODES = ("INSUFFICIENT_PERMISSIONS", "PERMISSION_DENIED")


@pytest.fixture(scope="module")
def real_settings():
    for k in ("LAU_BACKEND", "LAU_CONFIG_DIR", "LAU_STATE_DIR", "LAU_LOCAL_LAKE", "LAU_ENV_FILE"):
        os.environ.pop(k, None)
    from lau.settings import get_settings

    get_settings.cache_clear()
    s = get_settings()
    if s.project.backend != "databricks" or not s.state.warehouse_id:
        pytest.skip("workspace not initialised")
    return s


def _store(role, s):
    from lau.store import DatabricksStore

    return DatabricksStore(role, s)


@pytest.mark.parametrize("schema,table", DENY)
def test_agent_denied_by_unity_catalog(real_settings, schema, table):
    st = _store("agent", real_settings)
    try:
        with pytest.raises(Exception) as ei:
            st._query(f"SELECT * FROM {real_settings.fq(schema, table)} LIMIT 1")
        assert any(c in str(ei.value) for c in DENIED_CODES), str(ei.value)[:300]
    finally:
        st.close()


@pytest.mark.parametrize("schema,table", ALLOW)
def test_agent_allowed_only_granted_views(real_settings, schema, table):
    st = _store("agent", real_settings)
    try:
        assert len(st._query(f"SELECT * FROM {real_settings.fq(schema, table)} LIMIT 1")) == 1
    finally:
        st.close()


def test_agent_labels_view_is_train_only(real_settings):
    st = _store("agent", real_settings)
    try:
        df = st._query(f"SELECT DISTINCT split FROM {real_settings.fq('labels', 'labels_active')}")
        assert df["split"].tolist() == ["train"]
    finally:
        st.close()


def test_promoter_cannot_read_holdout_and_harness_can(real_settings):
    p, h = _store("promoter", real_settings), _store("harness", real_settings)
    try:
        with pytest.raises(Exception) as ei:
            p._query(f"SELECT * FROM {real_settings.fq('holdout', 'oot_labels')} LIMIT 1")
        assert any(c in str(ei.value) for c in DENIED_CODES)
        assert len(h._query(f"SELECT * FROM {real_settings.fq('holdout', 'oot_labels')} LIMIT 1")) == 1
    finally:
        p.close()
        h.close()


def test_agent_cannot_write_production(real_settings):
    st = _store("agent", real_settings)
    try:
        with pytest.raises(Exception) as ei:
            st._query(f"CREATE TABLE {real_settings.fq('production', 'x_probe')} AS SELECT 1 AS a")
        assert any(c in str(ei.value) for c in DENIED_CODES)
    finally:
        st.close()
