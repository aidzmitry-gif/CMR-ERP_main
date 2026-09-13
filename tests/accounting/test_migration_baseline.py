"""Static collision check; not a substitute for a full PostgreSQL upgrade."""
import ast
import re
from pathlib import Path


def test_proposal_does_not_recreate_registered_tables():
    registered = {}
    for path in Path("migrations/versions").glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8-sig"))
        for function in module.body:
            if not isinstance(function, ast.FunctionDef) or function.name != "upgrade":
                continue
            for call in ast.walk(function):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "create_table" and call.args
                        and isinstance(call.args[0], ast.Constant)):
                    continue
                schema = next((keyword.value.value for keyword in call.keywords
                               if keyword.arg == "schema" and isinstance(keyword.value, ast.Constant)), "public")
                registered[f"{schema}.{call.args[0].value}"] = path.name
    assert registered["logistics.import_shipment"] == "0023_logistics_sync.py"
    sql = Path("docs/accounting/schema-proposal.sql").read_text(encoding="utf-8")
    created = set(re.findall(r"CREATE TABLE\s+([\w.]+)", sql))
    assert created, "Proposal must contain table definitions"
    collisions = {name: registered[name] for name in created & registered.keys()}
    assert not collisions, f"Proposal recreates existing tables: {collisions}"
