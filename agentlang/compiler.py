"""Compile a small Python dialect with collection pipelines to standalone Python."""

import ast
import builtins
import io
import keyword
import tokenize
from functools import lru_cache
from pathlib import Path
from .helpers import SHARED_HELPERS


_FULL_HELPERS = {fn.__name__ for fn in SHARED_HELPERS.values()}
_SHORT_HELPERS = {name: fn.__name__ for name, fn in SHARED_HELPERS.items() if name != fn.__name__}
_SHORT_STAGES = {"w": "where", "m": "map", "f": "flat", "n": "count", "u": "sum",
                 "a": "mean", "s": "sort", "c": "common", "h": "first", "l": "list",
                 "k": "min", "x": "max", "t": "top"}
_COMMANDS = {"emit": "emit", "jsonout": "jsonout", "p": "emit", "j": "jsonout"}
_STAGE_IMPORTS = {
    "_ag_mean": "from statistics import mean as _ag_mean\n",
    "_ag_counter": "from collections import Counter as _ag_counter\n",
}

_STAGES = set(_SHORT_STAGES.values())
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
    if name in {"min", "max"}:
        key = f", key=lambda _: ({arg})" if arg else ""
        return f"_ag_builtins.{name}({source}{key})"
    if name == "top":
        if not arg:
            raise ValueError("top needs a count and optional key expression")
        spec = ast.parse(arg, mode="eval").body
        if isinstance(spec, ast.Tuple):
            if len(spec.elts) != 2:
                raise ValueError("top takes a count and one key expression")
            size, key = map(ast.unparse, spec.elts)
            return f"_ag_smallest({source}, ({size}), lambda _: ({key}))"
        return f"_ag_smallest({source}, ({arg}))"
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


def _expand_fields(source, filename):
    """Expand postfix string keys and record literals, preserving other source text."""
    if "$" not in source and "d{" not in source:
        return source
    offsets = [0]
    for line in io.StringIO(source):
        offsets.append(offsets[-1] + len(line))

    def offset(pos):
        return offsets[pos[0] - 1] + pos[1]

    def bad(message, token):
        raise SyntaxError(message, (filename, token.start[0], token.start[1] + 1, token.line))

    tokens = [t for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type not in _TRIVIA]
    changes = []
    i = 0
    while i + 1 < len(tokens):
        token, following = tokens[i:i + 2]
        if token.type in (tokenize.OP, tokenize.ERRORTOKEN) and token.string == "$":
            previous = tokens[i - 1] if i else None
            if (previous is None or previous.end != token.start or token.end != following.start
                    or following.type != tokenize.NAME):
                bad("use value$field for a literal string key", token)
            ends_atom = (previous.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING)
                         or previous.string in (")", "]", "}")
                         or previous.type == getattr(tokenize, "FSTRING_END", -1))
            if not ends_atom or (previous.type == tokenize.NAME and keyword.iskeyword(previous.string)
                                 and previous.string not in {"True", "False", "None"}):
                bad("a field lookup needs a value before '$'", token)
            changes.append((offset(token.start), offset(following.end), f"[{following.string!r}]"))
        elif (token.type == tokenize.NAME and token.string == "d" and following.string == "{"
              and token.end == following.start):
            changes.append((offset(token.start), offset(token.end), ""))
            i += 2
            while tokens[i].string != "}":
                field = tokens[i]
                if field.type != tokenize.NAME or keyword.iskeyword(field.string):
                    bad("d{...} takes comma-separated variable names", field)
                changes.append((offset(field.start), offset(field.end), f"{field.string!r}: {field.string}"))
                i += 1
                if tokens[i].string == "}":
                    break
                if tokens[i].string != ",":
                    bad("expected ',' or '}' in record literal", tokens[i])
                i += 1
        i += 1
    pieces = []
    start = 0
    for left, right, replacement in changes:
        pieces.extend((source[start:left], replacement))
        start = right
    pieces.append(source[start:])
    return "".join(pieces)


def _translate(source, filename):
    try:
        source = _expand_fields(source, filename)
    except tokenize.TokenError as exc:
        message, (line, col) = exc.args
        raise SyntaxError(message, (filename, line, col + 1, "")) from None
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
    names, aliases, shared = _bindings(tree, output, filename, stages)
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
        if index and index < len(tree.body) and tree.body[index].lineno == after:
            # A docstring or future import can share a line with executable code.
            # AST columns are UTF-8 byte positions, even for non-ASCII docstrings.
            line = lines[after - 1].encode("utf-8")
            column = tree.body[index - 1].end_col_offset
            rest = line[column:].decode("utf-8").lstrip(" \t").removeprefix(";").lstrip(" \t")
            lines[after - 1] = line[:column].decode("utf-8") + "\n" + prelude + "\n" + rest
        else:
            lines.insert(after, ("\n" if after else "") + prelude + "\n")
        output = "".join(lines)
    return output


def _bindings(tree, source, filename, stages):
    names, aliases = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in _SHORT_HELPERS:
                aliases[name] = _SHORT_HELPERS[name]
    # A helper can also be passed as a key function. Resolve first-class references
    # by lexical scope so a comprehension's local variable never pulls in a helper.
    possible = names.intersection(_SHORT_HELPERS).difference(aliases)
    if possible:
        import symtable
        scopes = [symtable.symtable(source, filename, "exec")]
        while scopes and possible:
            scope = scopes.pop()
            for name in possible.intersection(scope.get_identifiers()):
                symbol = scope.lookup(name)
                if symbol.is_global() and symbol.is_referenced() and not symbol.is_assigned():
                    aliases[name] = _SHORT_HELPERS[name]
                    possible.remove(name)
            scopes.extend(scope.get_children())
    if stages and "_ag_smallest" in names:
        aliases["_ag_smallest"] = "smallest"
    return names, aliases, _FULL_HELPERS.intersection(names).union(aliases.values())


def prepare_run(source, filename):
    """Compile once in memory and bind the same helpers used in standalone output."""
    output, _ = _translate(source, filename)
    tree = ast.parse(output, filename)
    names, aliases, shared = _bindings(tree, output, filename, stages=True)
    namespace = {name: SHARED_HELPERS[name] for name in shared}
    namespace.update((name, SHARED_HELPERS[target]) for name, target in aliases.items())
    if shared or "_ag_builtins" in names:
        namespace["_ag_builtins"] = builtins
    if "_ag_mean" in names:
        from statistics import mean
        namespace["_ag_mean"] = mean
    if "_ag_counter" in names:
        from collections import Counter
        namespace["_ag_counter"] = Counter
    return compile(tree, filename, "exec"), namespace
