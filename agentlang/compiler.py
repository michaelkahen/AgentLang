"""Compile a small Python dialect with collection pipelines to standalone Python."""

import ast
import io
import tokenize
from functools import lru_cache
from pathlib import Path


_IO_HELPERS = {"csvrows", "readjson", "writejson"}
_SHORT_HELPERS = {"r": "readjson", "c": "csvrows", "wj": "writejson"}
_SHORT_STAGES = {"w": "where", "m": "map", "f": "flat", "n": "count", "u": "sum",
                 "a": "mean", "s": "sort", "c": "common", "h": "first", "l": "list"}
_COMMANDS = {"emit": "emit", "jsonout": "jsonout", "p": "emit", "j": "jsonout"}
_STAGE_IMPORTS = {
    "_ag_mean": "from statistics import mean as _ag_mean\n",
    "_ag_counter": "from collections import Counter as _ag_counter\n",
}

_STAGES = {"where", "map", "flat", "count", "sum", "mean", "sort", "common", "first", "list"}
_TRIVIA = {tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.NL}


@lru_cache(maxsize=1)
def _helper_definitions():
    # Embed the same functions that a native Python caller can import.
    source = Path(__file__).with_name("helpers.py").read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    return {
        node.name: "".join(lines[node.lineno - 1:node.end_lineno])
        for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    }


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


def _command(statement):
    first = statement[0]
    if first.string not in _COMMANDS or len(statement) < 2:
        return None
    second = statement[1]
    if first.string in {"p", "j"}:
        # Preserve p(x), p[i], p.attr, assignments and ordinary augmented assignments.
        if second.start == first.end or second.string in {"is", "in", "and", "or", "not"}:
            return None
        if second.type == tokenize.OP and second.string not in {"(", "[", "{", "~", "+", "-"}:
            return None
    elif second.string in {"=", ":", "."}:
        return None
    return _COMMANDS[first.string]


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
    command = _command(statement)
    colon_allowed = bool(command or assignments or first.string == "return")
    if not colon_allowed and any(t.string == ":" for t in top):
        return None
    separators = []
    in_lambda = False
    for i in range(head_end, len(top) - 1):
        token = top[i]
        if token.string == "lambda":
            in_lambda = True
        if token.type != tokenize.OP:
            continue
        stage = top[i + 1].string
        if token.string == "|" and stage in _STAGES:
            separators.append(i)
        elif token.string == ":" and colon_allowed and not in_lambda and (stage in _SHORT_STAGES or stage in _STAGES):
            separators.append(i)
    first_pipe = separators[0] if separators else None
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

    # After the first recognized stage, catch unknown or incomplete stage names too.
    pipes = [] if first_pipe is None else [
        i for i in range(first_pipe, len(top))
        if top[i].type == tokenize.OP and top[i].string in {"|", ":"}
    ]
    expr_end = pos(top[pipes[0]].start) if pipes else end
    expr = source[expr_start:expr_end].strip()
    short_count = 0
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
            name = stage.string
            if top[pipe].string == ":" and name in _SHORT_STAGES:
                short_count += 1
                name = _SHORT_STAGES[name]
            expr = _stage(expr, name, arg)
    except ValueError as exc:
        raise SyntaxError(str(exc), (filename, first.start[0], first.start[1] + 1, first.line)) from None
    if command:
        fn = "_ag_builtins.print" if command == "emit" else "writejson"
        expr = f"{fn}({expr})"
    if pipes:
        # Drop redundant parentheses from the lowering so the emitted Python is readable.
        expr = ast.unparse(ast.parse(expr, filename, mode="eval").body)
    return start, end, prefix + expr, short_count


def compile_source(source, filename="<agentlang>"):
    """Return standalone Python with only the helper definitions this program uses."""
    output, _ = _translate(source, filename)
    return _with_helpers(output, filename, stages=True)


def count_short_stages(source):
    """Count actual one-letter stages using the same parser as the compiler."""
    _, count = _translate(source, "<agentlang>")
    return count


def _translate(source, filename):
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
    count = 0
    for left, right, replacement, short_count in edits:
        pieces.extend([source[start:left], replacement])
        start = right
        count += short_count
    pieces.append(source[start:])
    return "".join(pieces), count


def compile_python(source, filename="<python>"):
    """Validate native Python and supply exactly the shared I/O helper definitions."""
    return _with_helpers(source, filename, stages=False)


def _with_helpers(output, filename, stages):
    tree = ast.parse(output, filename)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    shared = _IO_HELPERS.intersection(names)
    # Short names are common loop variables. Only a direct function call requests an alias.
    callees = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    aliases = {name: target for name, target in _SHORT_HELPERS.items() if name in callees}
    shared.update(aliases.values())
    helpers = []
    if shared or (stages and "_ag_builtins" in names):
        helpers.append("import builtins as _ag_builtins\n")
    if stages:
        helpers.extend(code for name, code in _STAGE_IMPORTS.items() if name in names)
    if shared:
        helpers.extend(code for name, code in _helper_definitions().items() if name in shared)
        helpers.extend(f"{name} = {target}\n" for name, target in aliases.items())
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
