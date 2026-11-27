# Language reference

AgentLang accepts Python statements and expressions. A pipeline starts at the outer level of an assignment, a return, or an output statement. Each stage takes the previous result as input. Inside a stage expression, `_` is the current item.

```text
def mean_goal(rows, state):
    return rows:w _["state"] == state:a float(_["usd_goal_real"])
```

## Pipeline stages

The compact and long spellings produce the same operations. A compact stage starts with a colon. The full name can follow a pipe or a colon.

| Compact | Long | Result |
| --- | --- | --- |
| `:w EXPR` | `\| where EXPR` | Yield items satisfying the expression. |
| `:m EXPR` | `\| map EXPR` | Yield the expression for each item. |
| `:f EXPR` | `\| flat EXPR` | Yield each element of the iterable returned for each item. |
| `:n` | `\| count` | Count the items. |
| `:u` | `\| sum` | Sum the items. An optional expression transforms each item first. |
| `:a` | `\| mean` | Compute the arithmetic mean, optionally after applying an expression. |
| `:s` | `\| sort` | Return a stably sorted list. An optional expression supplies the key. |
| `:c N` | `\| common N` | Return up to N value/count pairs using `Counter.most_common`. |
| `:h` | `\| first` | Take the next item. Empty input raises `StopIteration`. |
| `:l` | `\| list` | Materialize the iterable as a list. |
| `:k EXPR`, `:x EXPR` | `\| min EXPR`, `\| max EXPR` | Select the first lowest- or highest-ranked item. Omit the expression to compare items directly. |
| `:t N, EXPR` | `\| top N, EXPR` | Take up to N lowest-ranked items in stable order. N is a nonnegative integer. The comma and key expression are optional. |

Filter, map, and flat-map are lazy. Collect the result with `:l` before JSON serialization or to iterate over it more than once. Assign a pipeline to a variable before using its result inside a larger expression. Use parentheses for Python bitwise expressions inside a stage. Python slices, dictionary literals, strings, and comments can contain colons.

## Working with records

`obj$field` means `obj["field"]`. Lookups can be chained or used in comprehensions, assignment targets, and pipeline expressions. The key must be an identifier touching the dollar sign on both sides (`row$person$name`). Use ordinary subscripts for dynamic keys, non-identifier keys, or integer indices. Inside formatted-string expressions, the shorthand requires Python 3.12 or later.

`obj?field` calls `obj.get("field")` once. For a dictionary, a missing key returns `None`. The receiver must supply a `get` method. Use `row.get("count", 0)` for an explicit default. Both `?` and `$` touch the receiver and the identifier key, and accept keyword spellings. In a chain such as `order$customer?email`, each operator applies to the preceding result.

`d{a,b}` constructs `{"a": a, "b": b}`. Mix local variables with computed fields using `name=expression`. For example, `d{total,orders=len(rows)}` expands to `{"total": total, "orders": len(rows)}`. Entries evaluate from left to right. Field names follow Python's variable naming rules. Use ordinary dictionary syntax for dynamic keys and unpacking.

```text
rows = r()
best = rows:x _$score
ids = rows:t 3, -_$score
top_ids = ids:m _$id:l
j d{best,top_ids}
```

## Input, output and shared functions

| Compact | Long | Behavior |
| --- | --- | --- |
| `r()`, `r(path)` | `readjson()`, `readjson(path)` | Parse standard input or a UTF-8 JSON file. |
| `c(path)` | `csvrows(path)` | Read a UTF-8 CSV into a list of dictionaries using the header as keys. Blank rows are skipped, missing cells become `None`, and extra cells are collected under the `None` key. |
| `wj(x)` | `writejson(x)` | Print one value using Python's default JSON formatting. |
| `p expr` | `emit expr` | Print the result of an expression or pipeline. |
| `j expr` | `jsonout expr` | Print the result as JSON. |
| `v(text, default=None)` | `parsevalue` | Parse JSON first, then Python literal syntax. Return the default on invalid input. Use `json.loads` when the input contract requires strict JSON syntax. |
| `b(value)` | `jsonbytes` | Serialize with Python's default JSON formatting followed by LF, encoded as UTF-8. |
| `h(data)` | `shahex` | SHA-256 hexadecimal digest of bytes. |
| `k(items, key=None)`, `x(items, key=None)` | `least`, `greatest` | Select the minimum or maximum item using an optional positional key function. Empty input raises `ValueError`. |
| `t(items, n, key=None)` | `smallest` | Stable selection of the n smallest items. Equivalent output to sorting and taking the first n for ordinary orderable keys. |

Use the short helper names in function calls. The same functions are importable from `agentlang.helpers` in ordinary Python. A short output command requires whitespace after its name. For example, `p x` prints a value and `p(x)` calls an ordinary Python name. Names beginning with `_ag_` are reserved for generated code.

## Compilation

The compiler expands record expressions, then checks for possible stage or output-command markers. When a marker is present, the statement parser identifies pipeline boundaries and lowers stages to Python generator expressions, built-ins, or standard-library calls. The `compile` command embeds the helper definitions in a standalone Python file. The `run` command compiles in memory and binds those functions directly, which avoids emitting and reparsing an intermediate file.

```sh
python3 -m agentlang compile examples/terse/paid_total.ag
python3 -m agentlang compile examples/terse/paid_total.ag -o /tmp/paid_total.py
```

For a model prompt, the [short reference](agent-reference.txt) collects the compact vocabulary. The measured comparison used a [shared helper card](../benchmarks/patterns/generation/operations.txt) and a [dialect addendum](../benchmarks/patterns/generation/syntax.txt).
