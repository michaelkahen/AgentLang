# AgentLang

AgentLang is an experimental Python dialect for short data-processing scripts. A small compiler expands pipelines into standalone Python that uses the standard library. The model can write a short program and a human can inspect or run the generated file.

```text
jsonout readjson() | sort _[1]
```

This script reads JSON pairs from standard input, sorts them by their second element, and prints the result. Sorting is stable, so equal scores keep their input order.

## Try it

From this directory, run the example with Python 3.10 or later. The compiler has no third-party dependencies.

```sh
python3 -m agentlang run examples/sort_scores.ag < examples/sort_scores.in
python3 -m agentlang compile examples/sort_scores.ag -o /tmp/sort_scores.py
python3 /tmp/sort_scores.py < examples/sort_scores.in
```

Relative paths in a program resolve from the working directory. The CSV examples expect to run from `examples/`. Installing the optional CLI makes that convenient.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
(cd examples && agentlang run goal_gap.ag)
```

## Language

Write normal Python functions, imports, expressions, and control flow. To use a pipeline, place it on its own line as an assignment, a return, or an output statement. Each stage consumes the previous result. Inside a stage expression, `_` represents the current item.

```text
def mean_goal(rows, state):
    return rows | where _["state"] == state | mean float(_["usd_goal_real"])
```

| Stage | Result |
| --- | --- |
| `where EXPR` | Yield items satisfying the expression. |
| `map EXPR` | Yield the expression evaluated on each item. |
| `flat EXPR` | Yield the elements of each iterable the expression returns. |
| `sum`, `mean` | Sum the items or take their arithmetic mean. An optional expression transforms each item first. |
| `count` | Count items, consuming the iterable. |
| `sort` | Return a sorted list. An optional expression supplies the sort key. |
| `common N` | Return up to N value/count pairs using `Counter.most_common`. |
| `first`, `list` | Take the next item or materialize the iterable. An empty input to `first` raises `StopIteration`. |

`emit expr` prints a value. `jsonout expr` prints it with Python's default JSON formatting. `readjson()` reads standard input, `readjson(path)` loads a UTF-8 file, and `csvrows(path)` loads a UTF-8 CSV into a list of dictionaries. `map`, `where`, and `flat` are lazy. Use `list` to collect their results before JSON serialization or to iterate over the results more than once.

Pipeline syntax operates at the outer level of an expression. To use a pipeline inside another expression, assign the pipeline result to a variable first. An outer `|` followed by a stage name selects that stage. Parenthesize Python unions and bitwise expressions when they would be ambiguous, such as `t = (int | list)`. Use a function with a `return` line for a pipeline inside a function body. Names starting with `_ag_` are reserved for the compiler.

## Measurements

Across four operations adapted from published agent tool calls, the compact scripts used **42.4% fewer tokens** than the standard-library Python versions and **14.4% fewer** than Python with the same I/O helpers. The precompiled scripts ran within 0.7 ms of the Python baselines. In 16 fresh model requests, compact code had a lower median generation time, while sending the grammar increased total service token usage. [Benchmark results and methodology](bench/RESULTS.md) · [Live generation trials](generation/README.md) · [Workload provenance](examples/PROVENANCE.md)

Run the tests from this directory. To repeat the runtime measurements, use the virtual environment with the `bench` extra installed. The resource sampler supports macOS and Linux.

```sh
python3 -m unittest discover -s tests -v
python bench/run.py --output /tmp/agentlang-seed.json
python bench/run.py --scale 1000 --output /tmp/agentlang-scaled.json
```
