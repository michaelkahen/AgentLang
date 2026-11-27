"""Compile a small Python dialect with collection pipelines to standalone Python."""

import ast
import builtins
import io
import keyword
import re
import tokenize
from functools import lru_cache
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
    "_ag_itemgetter": "from operator import itemgetter as _ag_itemgetter\n",
}

_LIST_STAGES = {"sort", "top", "common", "list"}
_LITERAL_ITEM_KEY = re.compile(r"""_[ \t\f\r\n]*\[[ \t\f\r\n]*('\w+'|"\w+"|[-+]?[0-9]+)[ \t\f\r\n]*\]""")

_STAGES = set(_SHORT_STAGES.values())
_STAGE_NAMES = _STAGES | _SHORT_STAGES.keys()
# A negative match rules out a statement rewrite. Positive matches, including
# text inside strings and comments, still go through the token-based parser.
# A backslash can join a separator and stage name across physical lines.
_STATEMENT_MARKERS = re.compile(
    rf"(?:^|;)[ \t\f]*(?:{'|'.join(_COMMANDS)})\b"
    rf"|[:|][ \t\f]*(?:{'|'.join(sorted(_STAGES | _SHORT_STAGES.keys()))})\b"
    r"|\\\r?\n", re.MULTILINE,
)
_TRIVIA = {tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.NL}
_ATOM_END_TYPES = {tokenize.NAME, tokenize.NUMBER, tokenize.STRING}
for _kind in ("FSTRING_END", "TSTRING_END"):
    if hasattr(tokenize, _kind):
        _ATOM_END_TYPES.add(getattr(tokenize, _kind))
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
                  ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
if hasattr(ast, "TypeAlias"):
    _NESTED_SCOPES += (ast.TypeAlias,)


@lru_cache(maxsize=1)
def _helper_definitions():
    # Embed the same functions that a native Python caller can import.
    from pathlib import Path

    source = Path(__file__).with_name("helpers.py").read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    return {
        node.name: "".join(lines[node.lineno - 1:node.end_lineno])
        for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    }


def _ranking_key(arg):
    if not arg or arg == "_":
        return ""
    # A literal key is independent of the surrounding Python scope. Keep
    # dynamic indexes and computed expressions inside the per-item callback.
    items = arg[1:-1] if arg.startswith("(") and arg.endswith(")") else arg
    keys = []
    for item in items.split(","):
        match = _LITERAL_ITEM_KEY.fullmatch(item.strip(" \t\f\r\n"))
        if not match:
            return f"lambda _: ({arg})"
        keys.append(match[1])
    return f"_ag_itemgetter({', '.join(keys)})"


def _stage(source, name, arg, previous=None):
    if name not in _STAGES:
        raise ValueError(f"unknown pipeline stage {name!r}")
    if name in {"where", "map", "flat", "common"} and not arg:
        raise ValueError(f"{name!r} needs an expression")
    if name in {"count", "first", "list"} and arg:
        raise ValueError(f"{name!r} takes no argument")
    source = f"({source})"
    if previous in _LIST_STAGES:
        if name == "count":
            return f"_ag_builtins.len({source})"
        if name == "list":
            return source
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
    if name in {"sort", "min", "max"}:
        fn = "sorted" if name == "sort" else name
        key = _ranking_key(arg)
        option = f", key={key}" if key else ""
        return f"_ag_builtins.{fn}({source}{option})"
    if name == "top":
        if not arg:
            raise ValueError("top needs a count and optional key expression")
        spec = ast.parse(arg, mode="eval").body
        if isinstance(spec, ast.Tuple):
            if len(spec.elts) != 2:
                raise ValueError("top takes a count and one key expression")
            size, key = map(ast.unparse, spec.elts)
            key = _ranking_key(key)
            option = f", {key}" if key else ""
            return f"_ag_smallest({source}, ({size}){option})"
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
    first = statement[0]
    # Compound headers (including type annotations) use ordinary Python.
    if first.string in {"def", "class", "async", "for", "while", "if", "elif", "with", "assert", "match", "case", "type"}:
        return None
    if first.string not in _COMMANDS and not any(t.string in (":", "|") for t in statement):
        return None

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

    start, end = pos(first.start), pos(statement[-1].end)
    assignments = [i for i, t in enumerate(top) if t.type == tokenize.OP and t.string == "="]
    head_end = assignments[0] + 1 if assignments else 0
    command = _command(statement)
    colon_allowed = bool(command or assignments or first.string == "return")
    if not colon_allowed and any(t.type == tokenize.OP and t.string == ":" for t in top):
        return None
    separators = []
    in_lambda = False
    for i in range(head_end, len(top) - 1):
        token = top[i]
        if token.type == tokenize.NAME and token.string == "lambda":
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
        assignments = [t for t in head if t.type == tokenize.OP and t.string == "="]
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
        if pipes and any(t.type == tokenize.NAME and t.string == "lambda" for t in head):
            raise ValueError("place the pipeline on a return line in a function, or parenthesize a lambda used as input")
        previous = None
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
            expr = _stage(expr, name, arg, previous)
            previous = name
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
    # This entry point has no subsequent Python parse to surface token errors.
    _, count = _translate(source, "<agentlang>", force_scan=True)
    return count


def _expand_fields(source, filename):
    """Expand postfix string keys and record literals, preserving other source text."""
    return _scan_fields(source, filename)[0]


def _field_receiver(token, last_key):
    if token.type == tokenize.NAME and keyword.iskeyword(token.string) and token is not last_key:
        return token.string in {"True", "False", "None"}
    return token.type in _ATOM_END_TYPES or token.string in (")", "]", "}", "...")


def _word_literal(stream, tokens, i, last_key, source, offset, bad):
    """Quote each identifier in place, preserving comments and physical lines."""
    marker, opening = tokens[i:i + 2]
    # Older tokenizers expose spaces before an invalid-Python sigil as tokens.
    j = i - 1
    while j >= 0 and tokens[j].type == tokenize.ERRORTOKEN and tokens[j].string.isspace():
        j -= 1
    if j >= 0 and _field_receiver(tokens[j], last_key):
        prev = tokens[j]
        head = tokens[j - 1] if j else None
        command = (prev.string in (*_COMMANDS, "match", "case")
                   and (head is None or head.type == tokenize.NEWLINE or head.string == ";"))
        stage = head and head.string in (":", "|") and prev.string in _STAGE_NAMES
        if prev.end == marker.start or not (command or stage):
            bad("use a word literal as a separate expression", marker)
    close = "]" if opening.string == "[" else ")"
    edits = [(offset(marker.start), offset(marker.end), "")]
    next(stream)  # the opening delimiter
    start = None
    for index, token in stream:
        if token.type == tokenize.OP and token.string == close:
            return edits
        if token.type == tokenize.ERRORTOKEN and token.string.isspace():
            continue
        if start is None:
            start = token
        after = tokens[index + 1]
        if token.end == after.start and after.string != close and not after.string.isspace():
            continue
        # The pre-3.12 tokenizer can split a Unicode identifier at combining marks.
        left, right = offset(start.start), offset(token.end)
        word = source[left:right]
        if not word.isidentifier():
            bad("word literals take whitespace-separated identifier keys", start)
        edits.append((left, right, repr(word) + ","))
        start = None
    bad(f"expected '{close}' to close word literal", opening)


def _scan_fields(source, filename):
    if "$" not in source and "?" not in source and "d{" not in source:
        return source, None
    offsets = [0]
    for line in io.StringIO(source):
        offsets.append(offsets[-1] + len(line))

    def offset(pos):
        return offsets[pos[0] - 1] + pos[1]

    def bad(message, token):
        raise SyntaxError(message, (filename, token.start[0], token.start[1] + 1, token.line))

    tokens = [t for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type not in _TRIVIA]
    changes = []
    depth = 0
    record_levels = []
    field_start = False
    lambda_params = 0
    last_key = None
    has_statement_marker = False
    stream = enumerate(tokens[:-1])
    for i, token in stream:
        name = token.string
        if token.type not in (tokenize.OP, tokenize.ERRORTOKEN) and not record_levels:
            if (depth == 0 and name in _COMMANDS and (i == 0 or tokens[i - 1].type == tokenize.NEWLINE
                                                      or tokens[i - 1].string == ";")):
                has_statement_marker = True
            continue
        following = tokens[i + 1]
        # A quoted ":s", slice, or dictionary value cannot start a pipeline.
        if depth == 0 and name in (":", "|") and following.string in _STAGE_NAMES:
            has_statement_marker = True
        elif depth and name == ";":
            # Let the statement parser diagnose a misplaced separator.
            has_statement_marker = True
        if field_start:
            field_start = False
            if token.type == tokenize.NAME and not keyword.iskeyword(name):
                if following.string == "=":
                    changes.append((offset(token.start), offset(token.end), repr(name)))
                    changes.append((offset(following.start), offset(following.end), ":"))
                elif following.string in {",", "}"}:
                    changes.append((offset(token.start), offset(token.end), f"{name!r}: {name}"))
                else:
                    bad("expected '=', ',' or '}' after record field", following)
            elif name != "}":
                bad("expected a variable name or name=expression in record literal", token)

        if token.type in (tokenize.OP, tokenize.ERRORTOKEN) and name in {"$", "?"}:
            previous = tokens[i - 1] if i else None
            if name == "$" and token.end == following.start and following.string in ("[", "("):
                changes.extend(_word_literal(stream, tokens, i, last_key, source, offset, bad))
                continue
            if (previous is None or previous.end != token.start or token.end != following.start
                    or following.type != tokenize.NAME):
                bad(f"use value{name}field for a literal string key", token)
            if not _field_receiver(previous, last_key):
                bad(f"a field lookup needs a value before '{name}'", token)
            last_key = following
            key = repr(following.string)
            replacement = f"[{key}]" if name == "$" else f".get({key})"
            if name == "?" and previous.type == tokenize.NUMBER:
                replacement = " " + replacement  # Keep the dot out of an integer literal.
            changes.append((offset(token.start), offset(following.end), replacement))

        if token.type == tokenize.OP and name in {"(", "[", "{"}:
            depth += 1
            previous = tokens[i - 1] if i else None
            if (name == "{" and previous is not None and previous.type == tokenize.NAME
                    and previous.string == "d" and previous.end == token.start):
                start = offset(previous.start)
                # In f"{d{x}}" erasing d must not produce an escaped "{{".
                spacer = " " if start and source[start - 1] == "{" else ""
                changes.append((start, offset(previous.end), spacer))
                record_levels.append((depth, lambda_params))
                lambda_params = 0
                field_start = True
        elif token.type == tokenize.OP and name in {")", "]", "}"}:
            if record_levels and depth == record_levels[-1][0]:
                _, lambda_params = record_levels.pop()
            depth -= 1
        elif record_levels and depth == record_levels[-1][0]:
            # Commas in an unparenthesized lambda's parameter list belong to
            # the expression. A lambda used as a default can nest another one.
            if token.type == tokenize.NAME and token is not last_key:
                if name == "lambda":
                    lambda_params += 1
                elif name == "for":
                    bad("enclose a comprehension or generator used as a record value", token)
            elif token.type == tokenize.OP and name == ":" and lambda_params:
                lambda_params -= 1
            elif token.type == tokenize.OP and name == "," and not lambda_params:
                field_start = True
    pieces = []
    start = 0
    for left, right, replacement in changes:
        pieces.extend((source[start:left], replacement))
        start = right
    pieces.append(source[start:])
    return "".join(pieces), has_statement_marker


def _translate(source, filename, *, force_scan=False):
    try:
        source, token_hint = _scan_fields(source, filename)
    except tokenize.TokenError as exc:
        message, (line, col) = exc.args
        raise SyntaxError(message, (filename, line, col + 1, "")) from None
    if not force_scan and (token_hint is False or not _STATEMENT_MARKERS.search(source)):
        return source, 0
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


def _binding_names(tree):
    """Collect identifiers and module-level calls without allocating a tuple for each AST node."""
    names, direct = set(), set()
    # Calls in a nested scope can be callbacks or comprehension targets. Only a
    # call in module scope may bypass lexical resolution of its function name.
    nested = []
    for module_scope, pending in ((True, [tree]), (False, nested)):
        while pending:
            node = pending.pop()
            # AST list fields may also contain strings or None.
            if not isinstance(node, ast.AST):
                continue
            if isinstance(node, ast.Name):
                names.add(node.id)
                continue
            if not node._fields or isinstance(node, ast.Constant):
                continue
            if module_scope and isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                direct.add(node.func.id)
            children = nested if module_scope and isinstance(node, _NESTED_SCOPES) else pending
            for field in node._fields:
                value = getattr(node, field, None)
                if isinstance(value, ast.AST):
                    children.append(value)
                elif isinstance(value, list):
                    children.extend(value)
    return names, direct


def _bindings(tree, source, filename, stages):
    names, direct = _binding_names(tree)
    candidates = SHARED_HELPERS.keys() & names
    needed = candidates & direct
    possible = candidates - needed
    if possible:
        import symtable
        scopes = [symtable.symtable(source, filename, "exec")]
        while scopes and possible:
            scope = scopes.pop()
            for name in possible.intersection(scope.get_identifiers()):
                symbol = scope.lookup(name)
                if (symbol.is_global() and symbol.is_referenced()
                        and (not symbol.is_assigned() or symbol.is_declared_global())):
                    needed.add(name)
                    possible.remove(name)
            scopes.extend(scope.get_children())
    aliases = {name: _SHORT_HELPERS[name] for name in sorted(needed & _SHORT_HELPERS.keys())}
    if stages and "_ag_smallest" in names:
        aliases["_ag_smallest"] = "smallest"
    return names, aliases, _FULL_HELPERS.intersection(needed).union(aliases.values())


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
    if "_ag_itemgetter" in names:
        from operator import itemgetter
        namespace["_ag_itemgetter"] = itemgetter
    return compile(tree, filename, "exec"), namespace
