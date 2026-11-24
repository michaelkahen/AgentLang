"""Identify actual syntax and observe shared helper calls on two correctness fixtures."""
import argparse
import ast
from collections import Counter
import inspect
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tokenize

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from agentlang import compile_python, compile_source, count_short_stages
import tiktoken
from agentlang.compiler import _SHORT_STAGES, _expand_fields
from agentlang.helpers import SHARED_HELPERS
from benchmarks.long.generation.run import monitored
from benchmarks.patterns.evaluation.cases import matches, prepare
from benchmarks.patterns.generation.run import ENCODING, atomic_write


# The actual shared implementations are known, even if a candidate shadows a one-letter alias.
HELPER_TREES = {
    f.__name__: ast.dump(ast.parse(inspect.getsource(f)).body[0])
    for f in SHARED_HELPERS.values()
}
HOOK = "_ag_study_observe"


def marker(kind, value):
    return ast.Call(func=ast.Name(id=HOOK, ctx=ast.Load()),
                    args=[ast.Constant(kind), value], keywords=[])


class MarkOperations(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        if node.name in HELPER_TREES and ast.dump(node) == HELPER_TREES[node.name]:
            after_docstring = int(ast.get_docstring(node) is not None)
            node.body.insert(after_docstring, ast.Expr(marker("helper_" + node.name, ast.Constant(None))))
            return node
        return self.generic_visit(node)

    def visit_Call(self, node):
        node = self.generic_visit(node)
        target = node.func
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if target.value.id == "_ag_builtins" and target.attr in {"min", "max"}:
                return marker("stage_" + target.attr, node)
        if isinstance(target, ast.Name) and target.id == "_ag_smallest":
            return marker("stage_top", node)
        return node


def annotate_syntax(source, arm):
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    lines = [0]
    for text in source.splitlines(keepends=True):
        lines.append(lines[-1] + len(text))

    def offset(pos):
        return lines[pos[0] - 1] + pos[1]

    edits, sites, spellings = [], Counter(), Counter()
    nstages = count_short_stages(source) if arm == "compact" else 0
    for i, (a, b) in enumerate(zip(tokens, tokens[1:])):
        if a.type == tokenize.NAME and a.string in SHARED_HELPERS and b.string == "(":
            spellings[a.string] += 1
        if arm != "compact" or a.end != b.start:
            continue
        if a.string == "$" and b.type == tokenize.NAME:
            sites["field"] += 1
            new = f"[{HOOK}('field', {b.string!r})]"
            edits.append((offset(a.start), offset(b.end), new))
        elif a.type == tokenize.NAME and a.string == "d" and b.string == "{":
            sites["record"] += 1
            close = next(t for t in tokens[i + 2:] if t.string == "}")
            edits.extend([(offset(a.start), offset(a.start), f"{HOOK}('record', "),
                          (offset(close.end), offset(close.end), ")")])
        elif nstages and a.string == ":" and b.string in _SHORT_STAGES:
            # Confirm against the compiler. A colon in a slice or dictionary is ordinary Python.
            equivalent = source[:offset(a.start)] + " | " + _SHORT_STAGES[b.string] + " " + source[offset(b.end):]
            try:
                replaced = count_short_stages(equivalent)
                same = ast.dump(ast.parse(compile_source(equivalent))) == ast.dump(ast.parse(compile_source(source)))
            except (SyntaxError, ValueError):
                continue
            if replaced == nstages - 1 and same:
                sites["stage_" + _SHORT_STAGES[b.string]] += 1
    if sum(x for k, x in sites.items() if k.startswith("stage_")) != nstages:
        raise ValueError("syntax audit did not reconcile with compiler stage count")
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        source = source[:start] + replacement + source[end:]
    return source, dict(sites), dict(spellings)


def instrument(source, arm):
    if HOOK in source:
        raise ValueError("observation identifier collides with submitted source")
    build = compile_python if arm == "python" else compile_source
    build(source, "<candidate>")  # Validate original program before annotating.
    annotated, sites, spellings = annotate_syntax(source, arm)
    tree = MarkOperations().visit(ast.parse(build(annotated, "<candidate>")))
    program = ast.unparse(ast.fix_missing_locations(tree))
    # Compile in an isolated namespace so future imports in the submitted program stay legal.
    wrapped = f"""import atexit, json
from collections import Counter
hits = Counter()
def observe(key, value):
    hits[key] += 1
    return value
def flush():
    with open('study-usage.json', 'w') as out:
        json.dump(hits, out)
atexit.register(flush)
scope = {{'__name__': '__main__', '__file__': __file__, {HOOK!r}: observe}}
exec(compile({program!r}, '<candidate>', 'exec'), scope)
"""
    return wrapped, sites, spellings


def observe_fixture(program, task, variant):
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        case = prepare(task, variant, work)
        (work / "candidate.py").write_text(program, encoding="utf-8")
        command = [sys.executable, "-I", "-B", "candidate.py"]
        if sys.platform == "darwin":
            policy = ("(version 1)(allow default)(deny network*)(deny file-write*)"
                      f"(allow file-write* (subpath {json.dumps(str(work.resolve()))}))")
            command = ["/usr/bin/sandbox-exec", "-p", policy, *command]
        output, _, metrics = monitored(command, case["stdin"], work, 12,
                                       env={"PATH": os.defpath, "HOME": temp, "LC_ALL": "C"})
        report = work / "study-usage.json"
        hits = json.loads(report.read_text()) if report.is_file() else {}
        correct = metrics["exit"] == 0 and matches(output, case["expected"])
    return {"correct": correct, "operations": hits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads(args.results.read_text(encoding="utf-8"))
    enc = tiktoken.get_encoding(ENCODING)
    records = []
    for row in run["trials"]:
        for attempt in row["attempts"]:
            rec = {k: row[k] for k in ("task", "arm", "round")}
            rec.update(attempt=attempt["attempt"], accepted=attempt["passed"], source_path=attempt["source_path"])
            records.append(rec)
            if not attempt["source_path"]:
                rec["status"] = "no source"
                continue
            path = Path(attempt["source_path"])
            path = (ROOT if path.parts[0] == "benchmarks" else args.results.parent) / path
            try:
                source = path.read_text(encoding="utf-8")
                program, sites, spellings = instrument(source, row["arm"])
                if row["arm"] == "compact":
                    expanded = _expand_fields(source, str(path))
                    rec["authored_tokens"] = len(enc.encode(source))
                    rec["expanded_field_and_record_tokens"] = len(enc.encode(expanded))
            except (ValueError, SyntaxError) as exc:
                rec["status"] = "unable to instrument: " + type(exc).__name__
                continue
            rec["syntax_sites"] = sites
            rec["helper_name_call_sites"] = spellings
            rec["checks"] = {v: observe_fixture(program, row["task"], v) for v in ("base", "edges")}
            rec["status"] = "observed"
    atomic_write(args.out, {"encoding": ENCODING, "fixtures": ["base", "edges"], "results": records})


if __name__ == "__main__":
    main()
