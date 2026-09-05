"""The layering rules, as assertions.

Phases 9 and 12 spent their effort removing framework coupling from the
business layer, and every phase since has re-checked it by hand. These tests
do it automatically, so the coupling cannot come back unnoticed.
"""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
    return modules


def imported_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {alias.name for alias in node.names}
    return names


def test_service_does_not_import_fastapi():
    """Phase 12's Definition of Done, kept honest.

    The service must stay usable by callers with no HTTP request: Phase 20's
    Excel importer, Phase 38's document extractor, and these tests.
    """
    modules = imported_modules(APP / "services" / "invoice_service.py")
    assert not [m for m in modules if m.split(".")[0] == "fastapi"]


def test_domain_exceptions_do_not_import_fastapi():
    """A status code is a transport's opinion, not a property of the error."""
    modules = imported_modules(APP / "core" / "exceptions.py")
    assert not [m for m in modules if m.split(".")[0] == "fastapi"]


def test_router_does_not_raise_http_exception():
    """Phase 12: routes raise meaning; error_handlers.py decides what it looks like."""
    assert "HTTPException" not in imported_names(APP / "routers" / "invoices.py")


def test_router_contains_no_sql():
    """Phase 8: persistence lives in the repository."""
    source = (APP / "routers" / "invoices.py").read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"add", "commit", "refresh", "scalars", "execute", "query"}


def test_only_config_reads_the_environment():
    """Phase 11: one source of configuration."""
    offenders = []
    for path in APP.rglob("*.py"):
        if path.name == "config.py":
            continue
        modules = imported_modules(path)
        if "os" in modules and "environ" in path.read_text():
            offenders.append(path.name)
    assert offenders == []
