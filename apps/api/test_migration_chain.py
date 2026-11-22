import importlib
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parent / "migrations" / "versions"


def test_migration_chain_is_linear_and_heads_at_08():
    revisions = {}
    for path in VERSIONS_DIR.glob("*.py"):
        module = importlib.import_module(
            f"apps.api.migrations.versions.{path.stem}"
        )
        revisions[module.revision] = module.down_revision

    assert set(revisions) == {
        "20261120_01",
        "20261120_02",
        "20261120_03",
        "20261120_04",
        "20261120_05",
        "20261120_06",
        "20261120_07",
        "20261122_09",
    }
    assert revisions["20261120_01"] is None
    for current in range(2, 8):
        revision = f"20261120_{current:02d}"
        assert revisions[revision] == f"20261120_{current - 1:02d}"
    assert revisions["20261122_09"] == "20261120_07"


def test_revision_01_bootstraps_users_for_empty_database():
    path = VERSIONS_DIR / "20261120_01_training_runs.py"
    source = path.read_text(encoding="utf-8")
    assert 'inspector.has_table("users")' in source
    assert 'op.create_table(\n            "users"' in source
    assert "zyrquen_migration_baseline" in source
