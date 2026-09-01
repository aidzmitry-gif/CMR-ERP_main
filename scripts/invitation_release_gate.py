"""Offline, secret-safe release gate for employee invitations.

This check deliberately reads only versioned source files.  It neither imports the
application nor evaluates environment variables, so it is safe to run in CI and
on an operator workstation before a production deployment.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REQUIRED_REVISIONS = ("0108", "0109", "0110")
REQUIRED_RUNBOOK_ENV_NAMES = (
    "AIOS_DATABASE_URL",
    "AIOS_KEYCLOAK_ISSUER",
    "AIOS_KEYCLOAK_AUDIENCE",
    "AIOS_KEYCLOAK_ADMIN_BASE_URL",
    "AIOS_KEYCLOAK_ADMIN_REALM",
    "AIOS_KEYCLOAK_ADMIN_CLIENT_ID",
    "AIOS_KEYCLOAK_ADMIN_CLIENT_SECRET",
    "AIOS_KEYCLOAK_INVITE_CLIENT_ID",
    "AIOS_KEYCLOAK_INVITE_REDIRECT_URI",
    "AIOS_KEYCLOAK_INVITE_LIFESPAN_SECONDS",
)


@dataclass(frozen=True)
class Migration:
    revision: str
    down_revisions: tuple[str, ...]
    has_real_downgrade: bool
    path: Path


def _literal_strings(node: ast.AST | None) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[str] = []
        for item in node.elts:
            values.extend(_literal_strings(item))
        return tuple(values)
    return ()


def _real_downgrade(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return true only when downgrade has an executable non-``pass`` statement."""
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    return bool(body) and not any(
        isinstance(node, ast.Pass) for node in ast.walk(ast.Module(body=body, type_ignores=[]))
    )


def _migration_from_file(path: Path) -> Migration | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ValueError(f"migration cannot be parsed: {path.name} ({type(exc).__name__})") from exc

    revision: str | None = None
    down_revisions: tuple[str, ...] = ()
    downgrade: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "revision":
                    values = _literal_strings(node.value)
                    revision = values[0] if len(values) == 1 else None
                if isinstance(target, ast.Name) and target.id == "down_revision":
                    down_revisions = _literal_strings(node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "downgrade":
            downgrade = node
    if revision is None:
        return None
    return Migration(
        revision=revision,
        down_revisions=down_revisions,
        has_real_downgrade=downgrade is not None and _real_downgrade(downgrade),
        path=path,
    )


def _iter_migrations(root: Path) -> Iterable[Migration]:
    versions = root / "migrations" / "versions"
    if not versions.is_dir():
        raise ValueError("migrations/versions is missing")
    for path in sorted(versions.glob("*.py")):
        migration = _migration_from_file(path)
        if migration is not None:
            yield migration


def _settings_source_checks(root: Path) -> list[str]:
    path = root / "config" / "settings.py"
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"settings.py cannot be parsed ({type(exc).__name__})"]

    settings = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings"),
        None,
    )
    if settings is None:
        return ["Settings class is missing"]

    values: dict[str, object] = {}
    validator_source = ""
    for node in settings.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant):
                values[node.target.id] = node.value.value
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_no_dev_defaults_in_prod"
        ):
            validator_source = ast.get_source_segment(source, node) or ""

    errors: list[str] = []
    if values.get("environment") != "prod":
        errors.append("settings default environment must be prod")
    if values.get("auth_mode") != "dev":
        errors.append("settings default auth_mode must remain dev for local/test opt-in")
    lifespan = values.get("keycloak_invite_lifespan_seconds")
    if not isinstance(lifespan, int) or lifespan < 300:
        errors.append("settings invite lifespan default must be at least 300 seconds")
    for expected, message in (
        ('self.auth_mode != "oidc"', "settings prod guard must require oidc"),
        (
            "not self.keycloak_issuer or not self.keycloak_audience",
            "settings prod guard must require issuer and audience",
        ),
        ('self.environment.lower().startswith("dev")', "settings prod guard must distinguish dev"),
    ):
        if expected not in validator_source:
            errors.append(message)
    return errors


def check_repository(root: Path) -> list[str]:
    """Return human-safe errors; never include file contents or env values."""
    errors: list[str] = []
    try:
        migrations = list(_iter_migrations(root))
    except ValueError as exc:
        return [str(exc)]

    by_revision: dict[str, Migration] = {}
    for migration in migrations:
        if migration.revision in by_revision:
            errors.append(f"duplicate migration revision: {migration.revision}")
        by_revision[migration.revision] = migration

    referenced = {revision for migration in migrations for revision in migration.down_revisions}
    heads = sorted(set(by_revision) - referenced)
    if len(heads) != 1:
        errors.append(f"expected exactly one Alembic head, found {len(heads)}")

    for revision in REQUIRED_REVISIONS:
        migration = by_revision.get(revision)
        if migration is None:
            errors.append(f"required invitation migration is missing: {revision}")
        elif not migration.has_real_downgrade:
            errors.append(f"required invitation migration lacks real downgrade: {revision}")

    runbook = root / "docs" / "EMPLOYEE_INVITATION_RUNBOOK.md"
    try:
        runbook_text = runbook.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        errors.append("employee invitation runbook is missing or unreadable")
    else:
        for name in REQUIRED_RUNBOOK_ENV_NAMES:
            if name not in runbook_text:
                errors.append(f"runbook is missing required environment variable name: {name}")
        for required_text in ("AIOS_ENVIRONMENT=prod", "AIOS_AUTH_MODE=oidc"):
            if required_text not in runbook_text:
                errors.append(f"runbook is missing required production gate: {required_text}")

    errors.extend(_settings_source_checks(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to inspect (default: script parent)",
    )
    args = parser.parse_args(argv)
    errors = check_repository(args.repo_root.resolve())
    if errors:
        print("Invitation release gate: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Invitation release gate: OK (offline source checks only; no secrets read)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
