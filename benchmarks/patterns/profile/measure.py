"""Attribute tokens in the archived long-program corpus and rank repeated source patterns."""

import argparse
import ast
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import io
import json
import keyword
from pathlib import Path
import sys
import tokenize

import tiktoken

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

ENCODING = tiktoken.get_encoding("o200k_base")
TAXONOMY = ("names", "strings", "operators", "keywords", "numbers", "layout", "comments")


def corpus():
    directory = ROOT / "benchmarks/long/generation"
    for series in ("observations", "required"):
        manifest = json.loads((directory / series / "results.json").read_bytes())
        for row in manifest["trials"]:
            if not row["passed"]:
                continue
            attempt = next(item for item in row["attempts"] if item["passed"])
            path = Path(attempt["source_path"])
            path = ROOT / path if path.parts[0] == "benchmarks" else directory / series / path
            yield series, row, path, path.read_bytes().decode()


def byte_offsets(source):
    starts = [0]
    lines = source.splitlines(keepends=True)
    for line in lines:
        starts.append(starts[-1] + len(line.encode()))
    return starts, lines


def inventory(source):
    raw = source.encode()
    regions = bytearray([TAXONOMY.index("layout")]) * len(raw)
    starts, lines = byte_offsets(source)

    def at(coord):
        row, col = coord
        return starts[row - 1] + len(lines[row - 1][:col].encode())

    kinds = {tokenize.STRING: "strings", tokenize.NUMBER: "numbers", tokenize.OP: "operators",
             tokenize.COMMENT: "comments"}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NAME:
            group = "keywords" if keyword.iskeyword(token.string) else "names"
        elif tokenize.tok_name[token.type].startswith("FSTRING"):
            group = "strings"
        else:
            group = kinds.get(token.type)
        if group:
            a, b = at(token.start), at(token.end)
            regions[a:b] = bytes([TAXONOMY.index(group)]) * (b - a)
    counts = Counter()
    anchors = []
    cursor = 0
    for value in ENCODING.encode(source, disallowed_special=()):
        blob = ENCODING.decode_single_token_bytes(value)
        assert raw[cursor:cursor + len(blob)] == blob
        anchor = next((i for i in range(cursor, cursor + len(blob))
                       if regions[i] != TAXONOMY.index("layout")), cursor)
        counts[TAXONOMY[regions[anchor]]] += 1
        anchors.append(anchor)
        cursor += len(blob)
    assert cursor == len(raw) and len(anchors) == sum(counts.values())
    return anchors, counts


def syntax_tree(source, compact):
    """Preserve native subtree coordinates and mark any replaced syntax as ineligible."""
    if not compact:
        return ast.parse(source), []
    try:
        return ast.parse(source), []
    except SyntaxError:
        pass

    # This is the complete subset of non-Python syntax in the frozen corpus.
    # Fail loudly if a future source introduces a different stage.
    edits = []
    starts = [0]
    for line in io.StringIO(source):
        starts.append(starts[-1] + len(line))

    def offset(coord):
        return starts[coord[0] - 1] + coord[1]

    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    depth = 0
    first = True
    assignment = False
    for index, tok in enumerate(tokens):
        if tok.type in {tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.NL}:
            continue
        if first and tok.string in {"j", "p"} and tok.end != tokens[index + 1].start:
            edits.append((offset(tok.start), offset(tok.end), "+"))
            assignment = True
        if first and tok.string == "return" or depth == 0 and tok.string == "=":
            assignment = True
        if not depth and assignment and tok.string == ":":
            stage = tokens[index + 1]
            if tok.end == stage.start and stage.type == tokenize.NAME:
                if stage.string not in {"w", "m", "f", "l", "n", "h"}:
                    raise ValueError(f"unexpected fused stage {stage.string!r}")
                replacement = "|0" if stage.string in {"l", "n", "h"} else "| "
                edits.append((offset(tok.start), offset(stage.end), replacement))
        if tok.type == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
        first = tok.type == tokenize.NEWLINE or tok.string == ";"
        if first:
            assignment = False
    projected = source
    for start, end, replacement in reversed(edits):
        projected = projected[:start] + replacement + projected[end:]
    assert len(source.encode()) == len(projected.encode())
    changed = [(len(source[:a].encode()), len(source[:b].encode())) for a, b, _ in edits]
    return ast.parse(projected), changed


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}"
    return "…"


def label(node):
    if isinstance(node, ast.Call):
        fn = dotted(node.func)
        name = fn.rsplit(".", 1)[-1]
        if fn in {"min", "max", "sorted"} and any(k.arg == "key" for k in node.keywords):
            return "keyed min, max or sort"
        if fn in {"r", "readjson", "wj", "writejson", "csvrows", "c"}:
            return "shared JSON and CSV I/O helpers"
        if name in {"sha256", "hexdigest"}:
            return "SHA-256 and hex digest calls"
        if name in {"append", "extend", "add", "update"}:
            return "collection mutation calls"
        if name in {"get", "setdefault", "items", "values", "keys"}:
            return "dictionary access methods"
        if fn in {"isinstance", "type"}:
            return "type tests"
        if name in {"encode", "decode"}:
            return "text/bytes encoding calls"
        if fn in {"json.dumps", "json.loads", "json.dump", "json.load", "ast.literal_eval"}:
            return "JSON or literal codecs"
        if fn in {"dict", "list", "tuple", "set", "Counter", "defaultdict"}:
            return "container construction"
        if fn in {"int", "str", "float", "bool"}:
            return "scalar conversions"
        if fn in {"sum", "any", "all", "len", "min", "max"}:
            return "built-in aggregations"
        if fn in {"range", "enumerate", "zip", "itertools.groupby", "groupby"}:
            return "iteration helpers"
        return None
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return "literal string field lookups"
        return "positional, dynamic or slice indexing"
    if isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
        return "comprehensions and generator expressions"
    if isinstance(node, ast.Dict):
        return "dictionary literals"
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and isinstance(getattr(node, "ctx", ast.Load()), ast.Load):
        return "tuple, list and set literals"
    if isinstance(node, ast.Lambda):
        return "lambda expressions"
    if isinstance(node, ast.Compare):
        return "comparisons"
    if isinstance(node, ast.IfExp):
        return "conditional expressions"
    if isinstance(node, ast.ExceptHandler):
        return "exception handler headers"
    if isinstance(node, (ast.For, ast.If, ast.With, ast.FunctionDef)):
        return {ast.For: "loop headers", ast.If: "if and elif headers", ast.With: "context manager headers",
                ast.FunctionDef: "function headers"}[type(node)]
    return None


def span(node, starts, lines):
    start = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    if isinstance(node, (ast.For, ast.If, ast.With, ast.FunctionDef, ast.ExceptHandler)):
        first = node.body[0]
        # Include multiline headers, stopping before the first line of the suite.
        end = (starts[first.lineno - 1] if first.lineno > node.lineno
               else starts[first.lineno - 1] + first.col_offset)
        if end > start and first.lineno > node.lineno:
            end -= len(lines[first.lineno - 2].encode()) - len(lines[first.lineno - 2].rstrip("\r\n").encode())
    return start, end


def patterns(source, is_compact, anchors):
    raw = source.encode()
    starts, lines = byte_offsets(source)
    root, changed = syntax_tree(source, is_compact)
    candidates = []
    for node in ast.walk(root):
        name = label(node)
        if not name:
            continue
        a, b = span(node, starts, lines)
        if not any(a < end and begin < b for begin, end in changed):
            candidates.append((name, a, b))
    # Own every token at most once. A nested idiom receives priority over its
    # enclosing lambda, comprehension, literal or statement header.
    owner = [None] * len(anchors)
    occurrences = Counter()
    occupied = defaultdict(set)
    samples = {}
    for name, a, b in sorted(candidates, key=lambda x: (x[1] - x[2], x[0])):
        left, right = bisect_left(anchors, a), bisect_left(anchors, b)
        owner[left:right] = [name] * (right - left)
        occupied[name].update(range(left, right))
        occurrences[name] += 1
        sample = " ".join(raw[a:b].decode().split())
        if name not in samples or abs(len(sample)-55) < abs(len(samples[name])-55):
            samples[name] = sample[:110]
    return occurrences, {k: len(v) for k, v in occupied.items()}, Counter(x for x in owner if x), samples


def profile():
    groups = {}
    for series, row, path, source in corpus():
        arm, task = row["arm"], row["task"]
        group = groups.setdefault(arm, dict(programs=[], lexical=Counter(), patterns={}))
        anchors, lex = inventory(source)
        occurrence, gross, exclusive, samples = patterns(source, arm == "compact", anchors)
        group["lexical"].update(lex)
        group["programs"].append(dict(series=series, task=task, round=row["round"], tokens=len(anchors),
                                      path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(source.encode()).hexdigest()))
        assert sum(exclusive.values()) <= len(anchors)
        for name, times in occurrence.items():
            out = group["patterns"].setdefault(name, dict(sites=0, programs=0, tasks=set(), gross_tokens=0,
                                                           exclusive_tokens=0, example=samples[name]))
            out["sites"] += times
            out["programs"] += 1
            out["tasks"].add(task)
            out["gross_tokens"] += gross[name]
            out["exclusive_tokens"] += exclusive[name]
    for group in groups.values():
        total = sum(group["lexical"].values())
        group["source_tokens"] = total
        group["unattributed_pattern_tokens"] = total - sum(p["exclusive_tokens"] for p in group["patterns"].values())
        group["patterns"] = dict(sorted(group["patterns"].items(), key=lambda p: -p[1]["exclusive_tokens"]))
        for values in group["patterns"].values():
            values["tasks"] = sorted(values["tasks"])
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "counts.json")
    args = parser.parse_args()
    groups = profile()
    report = dict(encoding=ENCODING.name, tiktoken=tiktoken.__version__, arms=groups)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for arm, group in groups.items():
        print(arm, len(group["programs"]), group["source_tokens"], group["lexical"])
        print([(k, v["exclusive_tokens"]) for k, v in list(group["patterns"].items())[:6]])


if __name__ == "__main__":
    main()
