"""Compile a small Python dialect with collection pipelines to standalone Python."""

import ast
import io
import tokenize


_PRELUDES = {
    "csvrows": '''import csv as _ag_csv


def csvrows(path):
    with _ag_builtins.open(path, encoding="utf-8", newline="") as stream:
        return _ag_builtins.list(_ag_csv.DictReader(stream))
''',
    "readjson": '''import json as _ag_json
import sys as _ag_sys


def readjson(path=None):
    if path is None:
        return _ag_json.load(_ag_sys.stdin)
    with _ag_builtins.open(path, encoding="utf-8") as stream:
        return _ag_json.load(stream)
''',
    "writejson": '''from json import dumps as _ag_dumps


def writejson(value):
    _ag_builtins.print(_ag_dumps(value))
''',
    "_ag_mean": "from statistics import mean as _ag_mean\n",
    "_ag_counter": "from collections import Counter as _ag_counter\n",
}

_STAGES = {"where", "map", "flat", "count", "sum", "mean", "sort", "common", "first", "list"}
_TRIVIA = {tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.NL}


def _stage(source, name, arg):
    if name not in _STAGES:
        raise ValueError(f"unknown pipeline stage {name!r}")
    if name in {"where", "map", "flat", "common"} and not arg:
        raise ValueError(f"{name!r} needs an expression")
    if name in {"count", "first", "list"} and arg:
        raise ValueError(f"{name!r} takes no argument")
    source = f"({source})"
    if name == "where":
        return f"(_ for _ in {source} if ({arg}))"
    if name == "map":
        return f"(({arg}) for _ in {source})"
    if name == "flat":
        return f"(_ag_item for _ in {source} for _ag_item in ({arg}))"
    if name == "count":
        return f"_ag_builtins.sum(1 for _ in {source})"
    if name in {"sum", "mean"}:
        fn = "_ag_builtins.sum" if name == "sum" else "_ag_mean"
        return f"{fn}(({arg}) for _ in {source})" if arg else f"{fn}({source})"
    if name == "sort":
        key = f", key=lambda _: ({arg})" if arg else ""
        return f"_ag_builtins.sorted({source}{key})"
    if name == "common":
        return f"_ag_counter({source}).most_common({arg})"
    if name == "first":
        return f"_ag_builtins.next(_ag_builtins.iter({source}))"
    return f"_ag_builtins.list({source})"


def _rewrite(statement, offsets, source, filename):
    """Rewrite a statement when a pipeline or output command is at the outer level."""
    def pos(coord):
        line, col = coord
        return offsets[line - 1] + col

    top = []
    depth = 0
    for token in statement:
        if depth == 0:
            top.append(token)
        if token.type == tokenize.OP:
            if token.string in ("(", "[", "{"):
                depth += 1
            elif token.string in (")", "]", "}"):
                depth -= 1

    first = statement[0]
    start, end = pos(first.start), pos(statement[-1].end)
    # Function annotations and the left of an assignment use ordinary Python unions.
    if first.string in {"def", "class", "async", "for", "while", "if", "elif", "with", "assert", "match", "case", "type"}:
        return None
    assignments = [i for i, t in enumerate(top) if t.string == "="]
    head_end = assignments[0] + 1 if assignments else 0
    if not assignments and any(t.string == ":" for t in top) and first.string not in {"emit", "jsonout", "return"}:
        return None
    first_pipe = next((i for i in range(head_end, len(top) - 1)
                       if top[i].string == "|" and top[i + 1].string in _STAGES), None)
    command = first.string if first.string in {"emit", "jsonout"} else None
    if len(top) > 1 and top[1].string in {"=", ":", "."}:
        command = None
    if first_pipe is None and command is None:
        return None

    head = top[:first_pipe]
    prefix = ""
    expr_start = start
    if first.string == "return" or command:
        expr_start = pos(first.end)
        if first.string == "return":
            prefix = "return "
    else:
        assignments = [t for t in head if t.string == "="]
        if assignments:
            expr_start = pos(assignments[-1].end)
            prefix = source[start:expr_start] + " "

    pipes = [] if first_pipe is None else [i for i in range(first_pipe, len(top)) if top[i].string == "|"]
    expr_end = pos(top[pipes[0]].start) if pipes else end
    expr = source[expr_start:expr_end].strip()
    try:
        if not expr:
            raise ValueError("expected an expression")
        if pipes and any(t.string == "lambda" for t in head):
            raise ValueError("place the pipeline on a return line in a function, or parenthesize a lambda used as input")
        for n, pipe in enumerate(pipes):
            if pipe + 1 == len(top):
                raise ValueError("expected a stage after '|'")
            stage = top[pipe + 1]
            stop = pos(top[pipes[n + 1]].start) if n + 1 < len(pipes) else end
            arg = source[pos(stage.end):stop].strip()
            expr = _stage(expr, stage.string, arg)
    except ValueError as exc:
        raise SyntaxError(str(exc), (filename, first.start[0], first.start[1] + 1, first.line)) from None
    if command:
        fn = "_ag_builtins.print" if command == "emit" else "writejson"
        expr = f"{fn}({expr})"
    if pipes:
        # Drop redundant parentheses from the lowering so the emitted Python is readable.
        expr = ast.unparse(ast.parse(expr, filename, mode="eval").body)
    return start, end, prefix + expr


def compile_source(source, filename="<agentlang>"):
    """Return standalone Python with only the helper definitions this program uses."""
    offsets = [0]
    for line in io.StringIO(source):
        offsets.append(offsets[-1] + len(line))
    edits = []
    statement = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in {tokenize.NEWLINE, tokenize.ENDMARKER} or (token.type == tokenize.OP and token.string == ";"):
                if statement:
                    edit = _rewrite(statement, offsets, source, filename)
                    if edit:
                        edits.append(edit)
                    statement.clear()
            elif token.type not in _TRIVIA:
                statement.append(token)
    except tokenize.TokenError as exc:
        message, (line, col) = exc.args
        raise SyntaxError(message, (filename, line, col + 1, "")) from None

    pieces = []
    start = 0
    for left, right, replacement in edits:
        pieces.extend([source[start:left], replacement])
        start = right
    pieces.append(source[start:])
    output = "".join(pieces)
    tree = ast.parse(output, filename)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    helpers = [code for name, code in _PRELUDES.items() if name in names]
    if names.intersection({"csvrows", "readjson", "writejson", "_ag_builtins"}):
        helpers.insert(0, "import builtins as _ag_builtins\n")
    prelude = "\n".join(helpers)
    if prelude:
        # Keep a module docstring and future imports ahead of injected definitions.
        index = 1 if ast.get_docstring(tree, clean=False) is not None else 0
        while index < len(tree.body) and isinstance(tree.body[index], ast.ImportFrom) and tree.body[index].module == "__future__":
            index += 1
        after = tree.body[index - 1].end_lineno if index else 0
        lines = output.splitlines(keepends=True)
        lines.insert(after, ("\n" if after else "") + prelude + "\n")
        output = "".join(lines)
    return output
