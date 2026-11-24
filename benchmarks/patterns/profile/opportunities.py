"""Apply fixed source-preserving rewrite rules to all archived long programs and replay."""

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import keyword
from pathlib import Path
import subprocess
import sys
import tempfile

from measure import HERE, ROOT, ENCODING, byte_offsets, corpus, dotted, syntax_tree
from agentlang import compile_python, compile_source
from benchmarks.long.workloads.cases import matches, prepare


@dataclass
class Rule:
    name: str
    edits: list


class Program:
    def __init__(self, source, compact):
        self.raw = source.encode()
        self.starts, _ = byte_offsets(source)
        self.tree, self.changed = syntax_tree(source, compact)
        self.parents = {child: node for node in ast.walk(self.tree) for child in ast.iter_child_nodes(node)}
        self.names = {n.id for n in ast.walk(self.tree)
                      if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.arg):
                self.names.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                self.names.add(node.name)
            elif isinstance(node, ast.alias):
                self.names.add(node.asname or node.name.split(".")[0])

    def start(self, n):
        return self.starts[n.lineno-1] + n.col_offset

    def end(self, n):
        return self.starts[n.end_lineno-1] + n.end_col_offset

    def segment(self, n):
        return self.raw[self.start(n):self.end(n)].decode()

    def wrapper(self, outer, arg, name):
        return [(self.start(outer), self.start(arg), name + "("), (self.end(arg), self.end(outer), ")")]

    def field(self, n):
        if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and isinstance(n.slice.value, str) and n.slice.value.isidentifier()
                and not keyword.iskeyword(n.slice.value)):
            return None
        # Locate only the bracket suffix; preserve parenthesized or nested bases.
        lead = self.raw[self.end(n.value):self.start(n.slice)]
        bracket = lead.rfind(b"[")
        if bracket < 0 or lead[bracket + 1:].strip() or self.raw[self.end(n.slice):self.end(n)].strip() != b"]":
            return None
        return Rule("string-key selector", [(self.end(n.value)+bracket, self.end(n), "$" + n.slice.value)])

    def pairs(self, n):
        if isinstance(n, ast.Dict):
            return [(k.value if isinstance(k, ast.Constant) else None, v) for k, v in zip(n.keys, n.values)]
        if isinstance(n, ast.Call) and dotted(n.func) == "dict" and not n.args and "dict" not in self.names:
            return [(k.arg, k.value) for k in n.keywords]
        return []

    def pack(self, n):
        pairs = self.pairs(n)
        if not pairs or not all(isinstance(v, ast.Name) and k == v.id for k, v in pairs):
            return None
        if len({k for k, _ in pairs}) != len(pairs):
            return None
        return Rule("pack named fields", [(self.start(n), self.end(n), "d{" + ", ".join(k for k, _ in pairs) + "}")])

    def mixed_records(self):
        records = fields = 0
        for node in ast.walk(self.tree):
            pairs = self.pairs(node)
            same = sum(isinstance(value, ast.Name) and key == value.id for key, value in pairs)
            if 0 < same < len(pairs):
                records += 1
                fields += same
        return dict(records=records, same_named_fields=fields)

    def codec(self, n):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.keywords:
            return None
        base = n.func.value
        if n.func.attr == "hexdigest" and not n.args and isinstance(base, ast.Call):
            if (dotted(base.func) == "hashlib.sha256" and len(base.args) == 1 and not base.keywords
                    and "h" not in self.names):
                return Rule("SHA-256 hex", self.wrapper(n, base.args[0], "h"))
        if (n.func.attr == "encode" and "b" not in self.names and isinstance(base, ast.BinOp)
                and isinstance(base.op, ast.Add) and isinstance(base.right, ast.Constant)
                and base.right.value == "\n" and isinstance(base.left, ast.Call)):
            j = base.left
            if (dotted(j.func) == "json.dumps" and len(j.args) == 1 and not j.keywords
                    and (not n.args or len(n.args) == 1 and isinstance(n.args[0], ast.Constant)
                         and n.args[0].value == "utf-8")):
                return Rule("JSON plus LF bytes", self.wrapper(n, j.args[0], "b"))
        return None

    def rank(self, n, stages, allow_top):
        upper = None
        call = n
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice):
            if not allow_top:
                return None
            sl = n.slice
            if sl.lower or sl.step or not isinstance(sl.upper, ast.Constant) or type(sl.upper.value) is not int or sl.upper.value < 0:
                return None
            upper, call = sl.upper.value, n.value
        if not isinstance(call, ast.Call) or len(call.args) != 1 or len(call.keywords) != 1:
            return None
        fn = dotted(call.func)
        if fn not in ({"sorted"} if upper is not None else {"min", "max"}) or fn in self.names:
            return None
        key = call.keywords[0]
        if key.arg != "key":
            return None
        arg, alias = call.args[0], {"min":"k", "max":"x", "sorted":"t"}[fn]
        parent = self.parents.get(n)
        outer = isinstance(parent, (ast.Return, ast.Assign, ast.AnnAssign)) and parent.value is n
        lam = key.value
        if stages and outer and isinstance(lam, ast.Lambda):
            params = lam.args
            if params.posonlyargs or len(params.args) != 1 or params.kwonlyargs or params.vararg or params.kwarg or params.defaults:
                return None
            var, body = params.args[0].arg, lam.body
            if any(isinstance(x, (ast.Lambda, ast.comprehension, ast.NamedExpr)) or
                   isinstance(x, ast.Name) and x.id == "_" and var != "_" for x in ast.walk(body)):
                return None
            edits = [(self.start(n), self.start(arg), ""),
                     (self.end(arg), self.start(body), ":" + alias + " " + (str(upper) + "," if upper is not None else "")),
                     (self.end(body), self.end(n), "")]
            edits.extend((self.start(x), self.end(x), "_") for x in ast.walk(body)
                         if isinstance(x, ast.Name) and x.id == var)
            return Rule("keyed " + ("top" if upper is not None else fn) + " stage", edits)
        if alias in self.names:
            alias = {"min":"least", "max":"greatest", "sorted":"smallest"}[fn]
        if alias in self.names:
            return None
        return Rule("shared keyed selection", [
            (self.start(n), self.start(arg), alias + "("),
            (self.end(arg), self.start(key.value), ", " + (str(upper) + ", " if upper is not None else "")),
            (self.end(key.value), self.end(n), ")")])

    def convert(self, *, codecs=True, rank=True, stages=False, fields=False, packs=False, top=False):
        edits, counts = [], Counter()
        for node in ast.walk(self.tree):
            if not hasattr(node, "end_lineno"):
                continue
            a, b = self.start(node), self.end(node)
            if any(a < y and x < b for x, y in self.changed):
                continue
            rule = self.codec(node) if codecs else None
            if not rule and rank:
                rule = self.rank(node, stages, top)
            if not rule and packs:
                rule = self.pack(node)
            if not rule and fields:
                rule = self.field(node)
            if rule:
                edits.extend((a, b, code.encode()) for a, b, code in rule.edits)
                counts[rule.name] += 1
        raw = self.raw
        right = len(raw)
        for a, b, replacement in sorted(edits, reverse=True):
            if b > right:
                raise RuntimeError("overlapping rewrite groups")
            raw = raw[:a] + replacement + raw[b:]
            right = a
        return raw.decode(), counts


def check(source, task, language, fixtures, sandbox):
    program = sandbox / "candidate.py"
    program.write_text((compile_source if language else compile_python)(source), encoding="utf-8")
    for variant, (folder, fixture) in fixtures[task].items():
        got = subprocess.run([sys.executable, "-I", "-B", str(program)], cwd=folder,
                             input=fixture["stdin"], capture_output=True, timeout=15)
        if got.returncode != 0 or not matches(got.stdout, fixture["expected"]):
            raise RuntimeError(f"{task}/{variant}: {got.stderr.decode(errors='replace')[-400:]} or output mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "opportunities.json")
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        sandbox, fixtures = Path(temp), {}
        for series, row, path, source in corpus():
            task, arm = row["task"], row["arm"]
            if task not in fixtures:
                fixtures[task] = {}
                for variant in ("base", "edges", "profile", "audit"):
                    folder = sandbox / task / variant
                    fixtures[task][variant] = (folder, prepare(task, variant, folder))
            program = Program(source, arm == "compact")
            record = dict(series=series, task=task, arm=arm, round=row["round"], path=str(path.relative_to(ROOT)),
                          original_tokens=len(ENCODING.encode(source)), mixed_records=program.mixed_records(), variants={})
            stages = dict(stages=True)
            selectors = dict(stages=True, fields=True)
            language = dict(stages=True, fields=True, packs=True)
            modes = {
                "as_written": dict(codecs=False, rank=False),
                "serialization_and_hash": dict(rank=False),
                "helpers_only": {},
                "add_extrema_stages": stages,
                "add_selectors": selectors,
                "helpers_and_language": language,
                "helpers_only_with_heap_top": dict(top=True),
                "helpers_and_language_with_heap_top": dict(**language, top=True),
            }
            validated = set()
            for mode, settings in modes.items():
                converted, counts = program.convert(**settings)
                use_language = arm == "compact" or settings.get("stages", False)
                try:
                    pair = converted, use_language
                    if pair not in validated:
                        check(converted, task, use_language, fixtures, sandbox)
                        validated.add(pair)
                except Exception as exc:
                    raise RuntimeError(f"{path.name} ({mode}): {exc}") from exc
                record["variants"][mode] = dict(tokens=len(ENCODING.encode(converted)), rewrites=counts,
                                                utf8_bytes=len(converted.encode()),
                                                sha256=hashlib.sha256(converted.encode()).hexdigest())
            rows.append(record)
    report = dict(encoding=ENCODING.name, fixtures_checked=["base","edges","profile","audit"], programs=rows)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for arm in ("python","compact"):
        subset = [r for r in rows if r["arm"] == arm]
        print(arm, sum(r["original_tokens"] for r in subset),
              {v:sum(r["variants"][v]["tokens"] for r in subset) for v in subset[0]["variants"]})


if __name__ == "__main__":
    main()
