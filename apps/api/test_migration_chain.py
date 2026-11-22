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
        "20261120_01": None,
        "20261120_02": "20261120_01",
        "20261120_03": "20261120_02",
        "20261120_04": "20261120_03",
        "20261120_05": "20261120_04",
        "20261120_06": "20261120_05",
        "20261120_07": "20261120_06",
        "20261121_08": "20261120_07",
        "20261122_09": "20261121_08",
    }
    assert revisions == expected


def test_revision_01_bootstraps_users_for_empty_database():
    path = VERSIONS_DIR / "20261120_01_training_runs.py"
    source = path.read_text(encoding="utf-8")
    assert 'inspector.has_table("users")' in source
    assert 'op.create_table(\n            "users"' in source
    assert "zyrquen_migration_baseline" in source


def test_revision_09_adds_api_key_rotation_columns_additively():
    path = VERSIONS_DIR / "20261122_09_api_key_rotation_metadata.py"
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20261121_08"' in source
    for column in (
        '"auto_rotate_enabled"',
        '"auto_rotate_interval_days"',
        '"last_rotated_at"',
        '"next_rotation_at"',
        '"rotation_count"',
    ):
        assert column in source
