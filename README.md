# AgentLang

I kept seeing coding agents write one-off Python scripts to get things done. Could an agent use fewer tokens and reach a correct result faster if it could write common operations in just one or two letters? I built AgentLang to test that idea against Python with the same helpers.

AgentLang is a work in progress. The current prototype compiles to standalone Python and uses the Python standard library.

```text
p r():w _$paid:u _$cents
```

This reads JSON orders from standard input, keeps the paid ones, sums their cents and prints the total. Here is the same calculation in Python with the shared input helper.

```python
print(sum(order["cents"] for order in r() if order["paid"]))
```

## Try it

Run the included example with Python 3.10 or later from the project root. It prints `350`.

```sh
printf '%s\n' '[{"paid":true,"cents":350},{"paid":false,"cents":900}]' \
  | python3 -m agentlang run examples/terse/paid_total.ag
```

To inspect the standalone Python, compile the same source. The output file can run on a machine with just Python installed.

```sh
python3 -m agentlang compile examples/terse/paid_total.ag -o /tmp/paid_total.py
```

## How it works

An ordinary Python statement can host a pipeline. The compiler binds `_` to the current item and translates stages to generator expressions, built-ins and standard-library calls. The script above uses `_$paid` to read a field, `:w` to filter and `:u` to sum. `r()` reads JSON, and `p` prints. The longer spelling `emit readjson() | where _["paid"] | sum _["cents"]` does the same work.

The compile command embeds the helper functions it needs in the output. The run command binds those functions in memory. Plain Python can also import these functions directly from `agentlang.helpers`. The benchmark preloads the same functions for both languages. [Language reference](docs/language.md) · [Short reference for agent prompts](docs/agent-reference.txt)

## What took the tokens?

We profiled 30 earlier agent-written programs. Operators and punctuation used **34.2%** of their 13,187 source tokens, identifiers **29.6%**, and string literals **15.2%**. Repeated constructs included bracketed field names, key functions for ranking, dictionary fields copied from local variables, and JSON serialization followed by a hash.

AgentLang now supports `event$run` for string-key lookup, `d{run,status}` for packing named fields and `rows:t 3,-_$score` for a stable top three. Both languages get `v` for parsing, `b` for JSON bytes, `h` for SHA-256, and `k`, `x`, `t` for keyed selection. On the fixed programs, the shared helpers saved 225 source tokens. The new syntax saved another 203 while keeping the algorithms fixed. [Profile and rewrite analysis](benchmarks/patterns/profile/README.md) · [Runnable ranking example](examples/terse/leaders.ag)

## Did it beat Python on total tokens and time?

**On individual scripts, Python used fewer total tokens. In four-script batches the AgentLang arm won both measures, but every batched submission was ordinary Python.** The model had the same helper functions in both arms. All 48 generated programs passed on the first attempt and passed a separate audit.

| Fixed comparison | Python tokens | AgentLang tokens | Python time | AgentLang time |
| --- | ---: | ---: | ---: | ---: |
| 16 individual scripts per language | **115,321** | 116,100 | 175.05 s | **170.71 s** |
| Two batches of four per language | 19,052 | **18,746** | 80.64 s | **70.41 s** |

Tokens include full service input and output. Time includes generation and validation through the first passing result. On individual scripts, the syntax instructions added 912 input tokens while output fell by 133. AgentLang finished sooner in 7 of 16 pairs. In batches, all eight AgentLang submissions passed unchanged under native Python with the same helpers. Two batch pairs give little evidence about future runs.

Sharing four tasks per request saved about **67% of total tokens for each language** against the corresponding individual rounds. Expanding only field and record syntax in the individually generated AgentLang programs showed a **3.1% source-token saving**. Across 512 local launches, fresh AgentLang scripts took a median 7.69 ms longer per pair. Prepared programs ran within 0.02 ms at the paired median. [Full comparison, CPU, memory and reproduction instructions](benchmarks/patterns/README.md)

The earlier [long-script study](benchmarks/long/README.md) found 7.6% fewer source tokens with mandatory one-letter stages, alongside 2.8% more total service tokens. The [short-script pilot](benchmarks/pilot/README.md) covers four smaller operations. Each experiment records its own model setup, helper contract and comparison groups.

## Explore the repository

| Path | What to look at |
| --- | --- |
| [Compiler](agentlang/compiler.py) | Stage recognition, Python translation and helper injection |
| [Pattern study](benchmarks/patterns/README.md) | Token inventory, fixed-source substitutions, live matched trials, batching and process measurements |
| [Long-script study](benchmarks/long/README.md) | Workloads, paired trials, repair budgets, independent verification and resource profiles |
| [Short-script pilot](benchmarks/pilot/README.md) | The original four-task experiment, including the Python helper control |
| [Runnable short example](examples/terse/paid_total.ag) | A complete stdin-to-stdout script |

The compiler runs from a checkout with no third-party dependencies. The following commands install the `agentlang` command and optional tokenizer, then run the tests.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
python -m unittest discover -s tests
python -m unittest benchmarks.long.workloads.test_cases benchmarks.patterns.evaluation.test_cases
```
