"""XJ-010/013: broad catches propagate, classify, or preserve a node-error cause.

Conservative AST control-flow check, not a proof of arbitrary Python execution.
Count a handler if any visible path returns, breaks/continues or falls through.
Nested function raises and conditional rethrows cannot excuse a swallowed path.
The frozen per-file allowances must only decrease; each retained site has a reason.
"""

import ast
import json
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
ALLOWLIST = Path(__file__).with_name("broad_except_allowlist.json")
CATEGORIES = {
    "app.core.errors." + name
    for name in (
        "AccessDenied", "ConflictError", "InvalidRequest", "StaleError", "TemporarilyUnavailable"
    )
}
BROAD_TYPES = {"Exception", "BaseException", "builtins.Exception", "builtins.BaseException"}
# Initial audited ceiling. JSON maintenance can lower counts, never add files or
# raise a count. Raising this ceiling requires a separately reviewed rule change.
INITIAL_ALLOWANCES = {
    "ai/diagnosis_graph.py": 1,
    "ai/governance.py": 4,
    "ai/reasoning.py": 1,
    "api/http_boundary.py": 1,
    "api/v1/routes/diagnosis_workflows.py": 2,
    "api/v1/routes/health.py": 1,
    "api/v1/routes/student.py": 1,
    "evaluation/context_runner.py": 1,
    "evaluation/workflow_runner.py": 1,
    "knowledge/case_drafting.py": 1,
    "services/diagnosis_workflow.py": 4,
    "services/query_sources.py": 2,
}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _symbol(node, aliases):
    name = _dotted(node)
    if name is None:
        return None
    parts = name.split(".")
    for length in range(len(parts), 0, -1):
        prefix = ".".join(parts[:length])
        if prefix in aliases:
            return ".".join([aliases[prefix], *parts[length:]])
    return name


def _aliases(tree, module):
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ClassDef):
            names[node.name] = f"{module}.{node.name}"
    # Imported constructor aliases (including aliases of aliases).
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            target = _symbol(node.value, names)
            if target and (target.startswith("app.") or target in BROAD_TYPES):
                for left in node.targets:
                    if isinstance(left, ast.Name) and names.get(left.id) != target:
                        names[left.id] = target
                        changed = True
        if not changed:
            break
    return names


def _classified(tree_records):
    classified = set(CATEGORIES)
    classes = [
        (f"{module}.{node.name}", [_symbol(base, aliases) for base in node.bases])
        for module, tree, aliases in tree_records
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    while True:
        extra = {name for name, bases in classes if any(base in classified for base in bases)}
        if extra <= classified:
            return classified
        classified |= extra


def _is_broad(node, aliases):
    if node is None:
        return True
    if isinstance(node, ast.Tuple):
        return any(_is_broad(item, aliases) for item in node.elts)
    return _symbol(node, aliases) in BROAD_TYPES


def _safe_exception(node, aliases, classified, instances):
    if isinstance(node, ast.Name) and node.id in instances:
        return True
    if isinstance(node, ast.Call):
        return _symbol(node.func, aliases) in classified
    if isinstance(node, ast.IfExp):
        return all(
            _safe_exception(part, aliases, classified, instances)
            for part in (node.body, node.orelse)
        )
    return False


def _visible_nodes(node):
    # A return/raise in a deferred function never terminates the exception block.
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _visible_nodes(child)


def _outcomes(body, aliases, classified, instances, caught_instances=None):
    outcomes = {"fallthrough"}
    instances = set(instances)
    caught_instances = set(instances if caught_instances is None else caught_instances)
    aliases = dict(aliases)
    for node in body:
        if "fallthrough" not in outcomes:
            break
        outcomes.remove("fallthrough")
        current = {"fallthrough"}
        if isinstance(node, ast.Raise):
            # XJ-013's observation envelope is propagation only when the original
            # caught instance is explicitly retained as its cause. This is not a
            # classified/retryable error and no other wrapper gets this exemption.
            observed = (
                isinstance(node.exc, ast.Call)
                and _symbol(node.exc.func, aliases)
                == "app.ai.diagnosis_graph.DiagnosisNodeExecutionError"
                and isinstance(node.cause, ast.Name)
                and node.cause.id in caught_instances
            )
            current = {
                "safe" if observed or node.exc is None or _safe_exception(
                    node.exc, aliases, classified, instances
                ) else "unsafe"
            }
        elif isinstance(node, (ast.Return, ast.Break, ast.Continue)):
            current = {"unsafe"}
        elif isinstance(node, ast.If):
            current = _outcomes(
                node.body, aliases, classified, instances, caught_instances
            ) | _outcomes(
                node.orelse, aliases, classified, instances, caught_instances
            )
            # A later envelope cannot prove retention of the caught instance if
            # a preceding branch may have rebound it (even to a classified error).
            for part in _visible_nodes(node):
                if isinstance(part, (ast.Assign, ast.AnnAssign)):
                    targets = part.targets if isinstance(part, ast.Assign) else [part.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            caught_instances.discard(target.id)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            safe = _safe_exception(node.value, aliases, classified, instances)
            for target in targets:
                if isinstance(target, ast.Name):
                    caught_instances.discard(target.id)
                    instances.discard(target.id)
                    if safe:
                        instances.add(target.id)
                    replacement = _symbol(node.value, aliases)
                    aliases[target.id] = replacement or "<unresolved>"
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Loops can run zero times; context managers/nested try can suppress
            # raises. Do not count their nested raises as guaranteed propagation.
            # Any explicit early return/yield also prevents a later rethrow.
            if any(isinstance(part, (ast.Return, ast.Yield, ast.YieldFrom))
                   for part in _visible_nodes(node)):
                current.add("unsafe")
        outcomes |= current
    return outcomes


def scan_broad_catches(sources):
    """Return {app-relative file: [line numbers]} without importing application code."""
    records = []
    for filename, source in sorted(sources.items()):
        module = "app." + filename.removesuffix(".py").replace("/", ".")
        tree = ast.parse(source, filename=filename)
        records.append((filename, module, tree, _aliases(tree, module)))
    classified = _classified([(module, tree, aliases) for _, module, tree, aliases in records])
    found = {}
    for filename, _, tree, aliases in records:
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and _is_broad(node.type, aliases)
            and _outcomes(node.body, aliases, classified, {node.name} if node.name else set())
            != {"safe"}
        ]
        if lines:
            found[filename] = sorted(lines)
    return found


def ratchet_errors(actual, allowed):
    errors = []
    for filename in sorted(actual.keys() | allowed.keys()):
        count, limit = len(actual.get(filename, [])), allowed.get(filename, 0)
        if count > limit:
            errors.append(
                f"{filename}: actual={count} allowlist={limit} lines={actual[filename]}; "
                "新增吞异常的宽泛捕获，请重新抛出或转成分类异常；禁止上调白名单"
            )
        elif count < limit:
            errors.append(f"{filename}: actual={count} allowlist={limit}; 请下调白名单")
    return errors


def test_broad_catches_match_downward_only_allowlist():
    document = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    allowed, reasons = document["files"], document["reasons"]
    assert allowed.keys() == reasons.keys()
    for filename, count in allowed.items():
        assert filename.endswith(".py") and not Path(filename).is_absolute()
        assert type(count) is int and count > 0
        assert count <= INITIAL_ALLOWANCES.get(filename, 0), "白名单只降不升"
        assert len(reasons[filename]) == count
        assert all(site["category"] in (1, 2, 3) and site["reason"] for site in reasons[filename])
    sources = {
        path.relative_to(APP_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in APP_ROOT.rglob("*.py")
    }
    actual = scan_broad_catches(sources)
    errors = ratchet_errors(actual, allowed)
    assert not errors, "宽泛异常棘轮门禁失败：\n" + "\n".join(errors)
    for filename, sites in reasons.items():
        assert sorted(site["line"] for site in sites) == actual[filename], (
            f"{filename}: 请更新既有位置的行号与理由，禁止为新增捕获增加白名单"
        )


@pytest.mark.parametrize(
    "catch, body, count",
    [
        ("Exception", "return None", 1),
        ("BaseException", "pass", 1),
        ("", "return 'stale'", 1),
        ("(Exception, ValueError)", "pass", 1),
        ("Exception", "raise", 0),
        ("Exception as exc", "raise exc", 0),
        ("Exception as exc", "raise ConflictError('conflict') from exc", 0),
        ("Exception", "error = Unavailable('retry')\n        raise error", 0),
        ("Exception", "if condition:\n            raise\n        return None", 1),
        ("Exception", "if condition:\n            raise\n        raise InvalidRequest('bad')", 0),
        ("Exception", "def deferred():\n            raise\n        return None", 1),
        ("Exception", "raise ValueError('stale')", 1),
        ("Exception", "raise HTTPException(status_code=503)", 1),
        ("Exception as exc", "exc = ValueError('bad')\n        raise exc", 1),
        ("Exception", "ConflictError = ValueError\n        raise ConflictError('bad')", 1),
        (
            "Exception",
            "try:\n            return None\n        finally:\n            pass\n        raise",
            1,
        ),
        ("E", "pass", 1),
        ("builtins.BaseException", "pass", 1),
    ],
)
def test_scanner_covers_propagation_and_swallowed_branches(catch, body, count):
    source = (
        "import builtins\nfrom builtins import Exception as E\n"
        "from app.core.errors import ConflictError, InvalidRequest\n"
        "from app.core.errors import TemporarilyUnavailable as Unavailable\n"
        "def scenario():\n    try:\n        operation()\n"
        f"    except {catch}:\n        {body}\n"
    )
    assert len(scan_broad_catches({"scenario.py": source}).get("scenario.py", [])) == count


def test_scanner_resolves_domain_subclasses_across_imports():
    sources = {
        "services/errors.py": (
            "from app.core.errors import ConflictError\n"
            "class VersionConflict(ConflictError, ValueError): pass\n"
        ),
        "services/client.py": (
            "from app.services.errors import VersionConflict as Conflict\n"
            "Alias = Conflict\n"
            "try: operation()\nexcept Exception as exc: raise Alias('changed') from exc\n"
        ),
    }
    assert scan_broad_catches(sources) == {}


@pytest.mark.parametrize("body,count", [
    ("raise NodeError('node', 1, 'TypeError') from exc", 0),
    ("raise NodeError('node', 1, 'TypeError')", 1),
    ("raise NodeError('node', 1, 'TypeError') from None", 1),
    ("exc = ValueError('replaced')\n        raise NodeError('node', 1, 'TypeError') from exc", 1),
    (
        "exc = ConflictError('replaced')\n        "
        "raise NodeError('node', 1, 'TypeError') from exc",
        1,
    ),
    ("if condition: return None\n        raise NodeError('node', 1, 'TypeError') from exc", 1),
    ("raise RuntimeError('node') from exc", 1),
    (
        "if condition: exc = ConflictError('replacement')\n        "
        "raise NodeError('node', 1, 'TypeError') from exc",
        1,
    ),
])
def test_only_explicit_cause_preserving_node_observation_is_propagation(body, count):
    source = (
        "from app.ai.diagnosis_graph import DiagnosisNodeExecutionError as NodeError\n"
        "from app.core.errors import ConflictError\n"
        "try: operation()\nexcept Exception as exc:\n    "
        + body.replace("\n        ", "\n    ") + "\n"
    )
    assert len(scan_broad_catches({"scenario.py": source}).get("scenario.py", [])) == count


def test_ratchet_blocks_growth_and_demands_reduction():
    assert "禁止上调白名单" in ratchet_errors({"new.py": [3]}, {})[0]
    assert "请下调白名单" in ratchet_errors({}, {"old.py": 1})[0]
    assert ratchet_errors({"same.py": [3]}, {"same.py": 1}) == []
