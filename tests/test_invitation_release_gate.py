from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "invitation_release_gate.py"
SPEC = importlib.util.spec_from_file_location("invitation_release_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _write_migration(path: Path, revision: str, down_revision: str | None, downgrade: str) -> None:
    down = "None" if down_revision is None else repr(down_revision)
    path.write_text(
        f'revision = "{revision}"\ndown_revision = {down}\n\n'
        "def upgrade():\n    return None\n\n"
        f"def downgrade():\n    {downgrade}\n",
        encoding="utf-8",
    )


def _fixture_repo(tmp_path: Path) -> Path:
    (tmp_path / "migrations" / "versions").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "config").mkdir()
    _write_migration(tmp_path / "migrations" / "versions" / "0107.py", "0107", None, "return None")
    _write_migration(
        tmp_path / "migrations" / "versions" / "0108.py", "0108", "0107", "return None"
    )
    _write_migration(
        tmp_path / "migrations" / "versions" / "0109.py", "0109", "0108", "return None"
    )
    _write_migration(
        tmp_path / "migrations" / "versions" / "0110.py", "0110", "0109", "return None"
    )
    (tmp_path / "docs" / "EMPLOYEE_INVITATION_RUNBOOK.md").write_text(
        "\n".join(
            (*gate.REQUIRED_RUNBOOK_ENV_NAMES, "AIOS_ENVIRONMENT=prod", "AIOS_AUTH_MODE=oidc")
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "settings.py").write_text(
        """class Settings:\n    environment: str = "prod"\n    auth_mode: str = "dev"\n    keycloak_invite_lifespan_seconds: int = 300\n\n    def _no_dev_defaults_in_prod(self):\n        if self.environment.lower().startswith("dev"):\n            return self\n        if self.auth_mode != "oidc":\n            raise ValueError()\n        if not self.keycloak_issuer or not self.keycloak_audience:\n            raise ValueError()\n        return self\n""",
        encoding="utf-8",
    )
    return tmp_path


def test_release_gate_accepts_current_repository() -> None:
    assert gate.check_repository(ROOT) == []


def test_release_gate_rejects_multiple_heads_and_pass_downgrade(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "migrations" / "versions" / "0110.py").write_text(
        'revision = "0110"\ndown_revision = "0109"\n\n'
        "def upgrade():\n    return None\n\n"
        "def downgrade():\n    pass\n",
        encoding="utf-8",
    )
    _write_migration(root / "migrations" / "versions" / "0999.py", "0999", "0108", "return None")

    errors = gate.check_repository(root)

    assert "expected exactly one Alembic head, found 2" in errors
    assert "required invitation migration lacks real downgrade: 0110" in errors


def test_release_gate_reports_missing_runbook_name_without_echoing_values(tmp_path: Path) -> None:
    root = _fixture_repo(tmp_path)
    (root / "docs" / "EMPLOYEE_INVITATION_RUNBOOK.md").write_text(
        "AIOS_ENVIRONMENT=prod\nAIOS_AUTH_MODE=oidc\n",
        encoding="utf-8",
    )

    errors = gate.check_repository(root)

    assert "runbook is missing required environment variable name: AIOS_KEYCLOAK_ISSUER" in errors
