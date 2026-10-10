"""What the package may import, which is not everything a developer has."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "socpuppet"


def test_nothing_in_the_package_imports_the_register_map_compiler():
    # The compiler is a developer's tool, as the linters are, and is not
    # installed with socpuppet: what it makes is checked in.
    importers = [
        str(module.relative_to(PACKAGE))
        for module in PACKAGE.rglob("*.py")
        if any(name.split(".")[0] == "systemrdl" for name in imports_of(module))
    ]

    assert importers == []


def imports_of(module):
    """Yield the name of each module that a Python file imports."""
    for node in ast.walk(ast.parse(module.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""
