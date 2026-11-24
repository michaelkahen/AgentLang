# AgentLang

AgentLang is a small language for agents that write one-off scripts. It compiles to standalone Python and uses the Python standard library. The experiment asks whether an agent can reach a correct result sooner by generating fewer tokens, even when ordinary Python gets the same helpers.

```text
p r():w _["paid"]:u _["cents"]
```

This reads JSON orders from standard input, keeps the paid ones, sums their cents and prints the total. Here is the same calculation in Python with the shared input helper.

```python
print(sum(order["cents"] for order in r() if order["paid"]))
```

## Try it

From the project root with Python 3.10 or later, run the example. It prints `350`.

```sh
printf '%s\n' '[{"paid":true,"cents":350},{"paid":false,"cents":900}]' \
  | python3 -m agentlang run examples/terse/paid_total.ag
```

To inspect the standalone Python, compile the same source. The output file can run on a machine with just Python installed.

```sh
python3 -m agentlang compile examples/terse/paid_total.ag -o /tmp/paid_total.py
```

## How it works

An ordinary Python statement can host a pipeline. The compiler binds `_` to the current item and translates stages to generator expressions, built-ins and standard-library calls. The script above uses `:w` to filter and `:u` to sum. `r()` reads JSON, and `p` prints. The longer spelling `emit readjson() | where _["paid"] | sum _["cents"]` does the same work.

The compiler embeds the helper functions it needs in the output. Plain Python can also import these functions directly from `agentlang.helpers`. The benchmark preloads the same functions for both languages. [Language reference](docs/language.md) · [Five-line reference for agent prompts](docs/agent-reference.txt)

## Benchmark results

We tested **30 agent-written programs, 40–87 lines each**, on three workloads adapted from executed agent code. The tasks cover a movie-credits join, a KNN parameter search and a fixture-packaging utility. All 30 passed on their first attempt and passed a separate unseen fixture. The table shows the **six matched pairs** in which the agent was asked to use the one-letter syntax. Python received the same preloaded helpers and short I/O aliases.

| Across six programs per language | Python + helpers | One-letter AgentLang |
| --- | ---: | ---: |
| Correct on first attempt | 6/6 | 6/6 |
| Generated source tokens | 2,637 | **2,437** |
| Total service tokens, input + output | **113,940** | 117,098 |
| Median time to a passing result | 12.26 s | **11.40 s** |

AgentLang used **7.6% fewer source tokens**, and its median time to pass was **7.0% lower**. It finished sooner in four of six pairs. The extra instructions and variation in the model client's input contributed to **2.8% more total service tokens**. In the other nine pairs the shorthand was optional. All nine AgentLang submissions used ordinary Python.

**What did shorter names actually buy?** Expanding the exact same six AgentLang programs to their long spellings took 2,473 source tokens. Compact spellings saved **36 tokens (1.46%)**. On the four short worked examples, the saving was **9.5%**. The rest of the live comparison reflects how the agent wrote each solution.

**Local CPU and memory also varied with the algorithm.** On larger inputs all three one-letter workloads had higher median fresh-process wall time than their Python controls. For KNN, CPU time was **107.89 vs. 63.80 ms**, and peak memory was **15.03 vs. 13.46 MiB**. One Python program reused neighbor rankings across the parameter grid. Its paired AgentLang program recomputed them.

[Per-task results, paired chart and replay commands](benchmarks/long/README.md) · [All 768 runtime measurements](benchmarks/long/runtime/README.md) · [Original agent scripts and adaptations](benchmarks/long/workloads/PROVENANCE.md)

## Explore the repository

| Path | What to look at |
| --- | --- |
| [Compiler](agentlang/compiler.py) | Stage recognition, Python translation and helper injection |
| [Long-script study](benchmarks/long/README.md) | Workloads, paired trials, repair budgets, independent verification and resource profiles |
| [Short-script pilot](benchmarks/pilot/README.md) | The original four-task experiment, including the Python helper control |
| [Runnable short example](examples/terse/paid_total.ag) | A complete stdin-to-stdout script |

The compiler runs from a checkout with no third-party dependencies. The following commands install the `agentlang` command and optional tokenizer, then run the tests.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
python -m unittest discover -s tests
python -m unittest benchmarks.long.workloads.test_cases
```
