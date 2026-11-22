import importlib
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parent / "migrations" / "versions"


def test_migration_chain_is_linear_and_heads_at_09():
    revisions = {}
    for path in VERSIONS_DIR.glob("*.py"):
        module = importlib.import_module(
            f"apps.api.migrations.versions.{path.stem}"
        )
        revisions[module.revision] = module.down_revision

    expected = {
        *(f"20261120_{number:02d}" for number in range(1, 8)),
        "20261121_08",
        "20261121_09",
    }
    assert set(revisions) == expected
    assert revisions["20261120_01"] is None

    ordered = [
        *(f"20261120_{number:02d}" for number in range(1, 8)),
        "20261121_08",
        "20261121_09",
    ]
    for previous, current in zip(ordered, ordered[1:]):
        assert revisions[current] == previous


def test_revision_01_bootstraps_users_for_empty_database():
    path = VERSIONS_DIR / "20261120_01_training_runs.py"
    source = path.read_text(encoding="utf-8")
    assert 'inspector.has_table("users")' in source
    assert 'op.create_table(\n            "users"' in source
    assert "zyrquen_migration_baseline" in source
