#!/usr/bin/env python3
"""Pre-commit hook: detect db.refresh() calls not wrapped in try/except.

This catches the most common pattern causing 500 errors in this codebase:

    await db.commit()
    await db.refresh(obj)  # ← will crash if relationships fail to load

The fix is to use safe_refresh() from backend.api.utils.db_helpers instead.
"""
import ast
import sys


def check_file(filepath: str) -> list[str]:
    """Return list of warning messages for unsafe db.refresh() calls."""
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filepath)
    except (SyntaxError, UnicodeDecodeError):
        return []

    warnings = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        # Match: await db.refresh(...) or await self.db.refresh(...)
        if isinstance(func, ast.Attribute) and func.attr == "refresh":
            # Check if this call is inside a try/except
            if not _is_inside_try(tree, node):
                # Also allow if the function name contains "safe"
                if isinstance(func.value, ast.Name) and "safe" in func.value.id.lower():
                    continue
                warnings.append(
                    f"{filepath}:{node.lineno}: db.refresh() outside try/except — "
                    f"use safe_refresh() from backend.api.utils.db_helpers"
                )

    return warnings


def _is_inside_try(tree: ast.AST, target_node: ast.AST) -> bool:
    """Check if target_node is inside a Try block's body or handlers."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                if child is target_node:
                    return True
    return False


def main():
    exit_code = 0
    for filepath in sys.argv[1:]:
        if not filepath.endswith(".py"):
            continue
        # Skip test files and the safe_refresh helper itself
        if "/tests/" in filepath or "db_helpers" in filepath:
            continue
        for warning in check_file(filepath):
            print(warning)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
