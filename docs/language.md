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

Filter, map, and flat-map are lazy. Collect the result with `:l` before JSON serialization or to iterate over it more than once. Assign a pipeline to a variable before using its result inside a larger expression. Use parentheses for Python bitwise expressions inside a stage. Python slices, dictionary literals, strings, and comments can contain colons.

## Input and output

| Compact | Long | Behavior |
| --- | --- | --- |
| `r()`, `r(path)` | `readjson()`, `readjson(path)` | Parse standard input or a UTF-8 JSON file. |
| `c(path)` | `csvrows(path)` | Read a UTF-8 CSV into a list of dictionaries using the header as keys. |
| `wj(x)` | `writejson(x)` | Print one value using Python's default JSON formatting. |
| `p expr` | `emit expr` | Print the result of an expression or pipeline. |
| `j expr` | `jsonout expr` | Print the result as JSON. |

Use the short helper names in function calls. The same functions are importable from `agentlang.helpers` in ordinary Python. A short output command requires whitespace after its name. For example, `p x` prints a value and `p(x)` calls an ordinary Python name. Names beginning with `_ag_` are reserved for generated code.

## Compilation

The compiler tokenizes each statement, identifies outer pipeline boundaries, and lowers stages to Python generator expressions, built-ins, or standard-library calls. It embeds the definitions of the I/O helpers it needs. The resulting file runs on Python without installing AgentLang.

```sh
python3 -m agentlang compile examples/terse/paid_total.ag
python3 -m agentlang compile examples/terse/paid_total.ag -o /tmp/paid_total.py
```

For a model prompt, the [short reference](agent-reference.txt) collects the compact vocabulary on five lines.
