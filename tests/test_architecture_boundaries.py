import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "src" / "jobpicky"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            result.add(prefix + (node.module or ""))
    return result


def test_core_does_not_depend_on_entry_points_or_feishu() -> None:
    forbidden = {"..web", "..cli", "..feishu", "..integrations"}
    for path in (ROOT / "core").glob("*.py"):
        imports = _imports(path)
        assert not any(
            name in forbidden or any(name.startswith(prefix + ".") for prefix in forbidden)
            for name in imports
        ), (path, imports)


def test_web_routes_do_not_import_business_implementation_modules() -> None:
    imports = _imports(ROOT / "web" / "app.py")
    forbidden = {"..storage", "..matcher", "..wondercv", "..seed", "..pipeline"}
    assert imports.isdisjoint(forbidden)


def test_primary_cli_flows_delegate_to_shared_services() -> None:
    source = (ROOT / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: ast.get_source_segment(source, node) or "" for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "run_daily_workflow(" in functions["_run_daily"]
    assert "rematch_local(" in functions["_run_rematch"]


def test_feishu_connection_does_not_run_local_initialization() -> None:
    source = (ROOT / "integrations" / "feishu" / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    connect = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "connect")
    called = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id for node in ast.walk(connect) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))}
    assert called.isdisjoint({"initialize", "crawl", "rematch_all", "rebuild_all"})
