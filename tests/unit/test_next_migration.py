from scripts import coordination_hook, next_migration


def test_head_prefers_real_head_over_stale_reservation():
    assert next_migration._head(
        {"0090", "0105", "0106"},
        {"0090", "0105"},
        [(90, "0090")],
    ) == "0106"


def test_head_uses_newer_reservation_after_real_head():
    assert next_migration._head(
        {"0105", "0106"},
        {"0105"},
        [(107, "0106")],
    ) == "0107"


def test_head_uses_nonnumeric_alembic_tip_when_no_numeric_tip_exists():
    assert next_migration._head({"base", "merge_tip"}, {"base"}, []) == "merge_tip"


def test_scan_tracks_tuple_list_and_none_down_revisions(tmp_path, monkeypatch):
    migrations = tmp_path / "versions"
    migrations.mkdir()
    (migrations / "0128_base.py").write_text('revision = "0128"\ndown_revision = None\n', encoding="utf-8")
    (migrations / "0129_crm.py").write_text('revision = "0129"\ndown_revision = "0128"\n', encoding="utf-8")
    (migrations / "0132_accounting.py").write_text('revision = "0132"\ndown_revision = ["0130", "0131"]\n', encoding="utf-8")
    (migrations / "0133_merge.py").write_text('revision = "0133"\ndown_revision = ("0129", "0132")\n', encoding="utf-8")
    (migrations / "0137_mapping.py").write_text('revision = "0137"\ndown_revision = "0133"\n', encoding="utf-8")
    monkeypatch.setattr(next_migration, "MIGR", migrations)

    revs, downs = next_migration._scan()

    assert revs == {"0128", "0129", "0132", "0133", "0137"}
    assert downs == {"0128", "0129", "0130", "0131", "0132", "0133"}
    assert next_migration._head(revs, downs, []) == "0137"


def test_coordination_hook_accepts_the_same_merge_history(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations" / "versions"
    migrations.mkdir(parents=True)
    (migrations / "0128_base.py").write_text('revision = "0128"\ndown_revision = None\n', encoding="utf-8")
    (migrations / "0129_crm.py").write_text('revision = "0129"\ndown_revision = "0128"\n', encoding="utf-8")
    (migrations / "0132_accounting.py").write_text('revision = "0132"\ndown_revision = ["0130", "0131"]\n', encoding="utf-8")
    (migrations / "0133_merge.py").write_text('revision = "0133"\ndown_revision = ("0129", "0132")\n', encoding="utf-8")
    (migrations / "0137_mapping.py").write_text('revision = "0137"\ndown_revision = "0133"\n', encoding="utf-8")
    monkeypatch.setattr(coordination_hook, "_git", lambda *_args: str(tmp_path))

    assert coordination_hook._alembic_heads() == ["0137"]
