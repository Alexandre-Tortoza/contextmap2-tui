from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parents[2] / "src" / "contextmap_tui"
HEAVY_ROOTS = {
    "rosbags",
    "rospy",
    "rclpy",
    "torch",
    "transformers",
    "cv2",
    "open3d",
}
FORBIDDEN_CONTEXTMAP_SEGMENTS = {"backends", "infrastructure", "adapters"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def _violations(path: Path, module: str) -> list[str]:
    root = module.split(".", maxsplit=1)[0]
    violations: list[str] = []
    if root in HEAVY_ROOTS:
        violations.append(f"{path}: heavy/source SDK import is forbidden: {module}")
    if root == "contextmap":
        relative = path.relative_to(SRC_ROOT)
        in_integration_boundary = relative.parts[0] == "integration"
        if not in_integration_boundary:
            violations.append(
                f"{path}: contextmap may only be imported from contextmap_tui/integration: {module}"
            )
        if FORBIDDEN_CONTEXTMAP_SEGMENTS.intersection(module.split(".")):
            violations.append(f"{path}: ContextMap2 internals/backends are forbidden: {module}")
    return violations


def test_source_imports_preserve_tui_core_boundary() -> None:
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for module in _imports(path):
            violations.extend(_violations(path, module))

    assert violations == []


def test_rule_rejects_representative_forbidden_imports() -> None:
    regular = SRC_ROOT / "screens" / "bad.py"
    integration = SRC_ROOT / "integration" / "bad.py"

    assert _violations(regular, "rosbags.highlevel")
    assert _violations(regular, "contextmap.ingestion")
    assert _violations(integration, "contextmap.visual_perception.backends.sam3")
    assert _violations(integration, "contextmap.ingestion") == []
