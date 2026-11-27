# Scripting optimization, second round

**November 27, 2026.** The comparison starts at `0e896bc`, the completed [first scripting study](../scripting/README.md). All timing tables use an Apple M1 running macOS 14.8.2 and CPython 3.12.4. Python 3.10.22 and 3.14.10 provided independent compatibility replays.

The compiler improvements benefit existing programs. Fresh launches now avoid argument-parser setup for ordinary `run file.ag` invocations, and scripts using record syntax often need only one tokenization pass. For newly written scripts, `$[team name score]` produces a list of strings and `$(queued running)` a tuple. The largest token savings occur in code that declares schemas, columns or states. [Language reference](../../docs/language.md) · [Runnable score table](../../examples/terse/score_table.ag)

## Complete script launches

All 16 archived AgentLang programs for the movie join, KNN grid, fixture packaging and trace replay ran on their audit and larger profile inputs. The harness alternated the two releases in balanced order, with one warmup and eight measured launches per release, program and fixture. All 512 timed outputs and 64 warmups passed the independent oracle. Each launch started a fresh interpreter. Filesystem and bytecode caches could warm.

| Fixture | Median paired wall-time change | Programs with lower wall time | Median paired process CPU change |
| --- | ---: | ---: | ---: |
| Audit | −11.7% | 16 / 16 | −12.4% |
| Larger profile | −6.0% | 11 / 16 | −5.8% |

For each program we divided its updated median by its previous median, then took the median of the 16 ratios. Median paired wall-time differences were −5.70 ms and −6.65 ms. The median percentage improvement was smaller when the programs processed more data. All 16 audit scripts and 12 of 16 profile scripts used less process CPU. Four workload families and one host limit generalization. [Launch harness](../scripting/launches.py) · [All paired timings and package hashes](results/launches.json)

An additional 216 measured launches compared ordinary dispatch, full argument parsing via an explicit option separator, and precompiled Python. On the three small examples, direct dispatch saved 4.2–6.6 ms of median process CPU with normal interpreter startup, and 9.2–11.2 ms with site initialization disabled. Precompiled Python had the lowest median in all six cells. The ordinary run path still resolves the real source location and passes script arguments through. Help, option separators and dash-prefixed filenames use the full parser. [Dispatch experiment](dispatch.py) · [Individual samples](results/dispatch.json)

## Which spelling transfers to complete scripts?

We sampled 131,072 distinct fragments from eight contexts, eight vocabularies and six sequence lengths, from two to twelve words. Vocabularies included Unicode. Each fragment had eight renderings, yielding **1,048,576 source renderings** measured with both `o200k_base` and `cl100k_base`. The controls included quoted literals, quotes without separator spaces, and splitting a string at runtime. We checked 4,096 sampled literal values and types. [Generator, controls and rewrite rules](spellings.py) · [Counts for both encoders](results/spellings.json)

| Corpus · o200k | Previous source | Best existing control¹ | Word lists and tuples | Saved vs control |
| --- | ---: | ---: | ---: | ---: |
| 131,072 generated fragments | 3,416,346 | 2,256,426 | 2,017,285 | 10.60% |
| 76 archived submissions | 25,921 | 25,837 | 25,763 | 0.29% |
| 29 repository tools | 44,675 | 44,546 | 44,430 | 0.26% |
| 16 held-out batch scripts | 6,381 | 6,351 | 6,324 | 0.43% |
| 8 package and test files | 10,563 | 10,562 | 10,561 | 0.01% |

¹ The generated baseline uses the shortest existing form for each fragment. The complete-script experiment starts from the previous study's record rewrites and preserves all surrounding source. The control compares existing spellings on each complete program. A `.split()` spelling is a token-cost control whose construction executes at runtime. Equivalence for the shipped spelling was checked against ordinary literals.

On `cl100k_base`, the new spelling used 10.01% fewer tokens than the best generated control. Sixty generated fragments were longer on that encoder. On the held-out batch the two encoders both saved 57 tokens against the previous source, or 27 against the best existing control. Twenty-one interleaved preparation pairs per affected held-out script found a median extra CPU cost of 0.002 ms across the ten batch programs that used the spelling. The 129 full-program pairs compiled to identical Python syntax trees on each of three interpreters. The compact reference covers the new forms in 203 o200k tokens and 201 cl100k tokens, three fewer on each than the previous card. These are local source and reference-text measurements. Model generation quality, service usage and time to first correct script remain unmeasured. [Compact reference](../../docs/agent-reference.txt)

## Where compilation got faster

The field scanner already knows whether a colon or pipe appears at statement depth. Reusing that information avoids a second tokenization pass when a possible marker appears only in data, quoted text or comments. Statements that cannot contain a pipeline can also bypass the detailed pipeline parser. Helper lookup uses separate work lists for module and nested scopes, skips leaves and retains Python's symbol-table resolution for ambiguous bindings.

| Same source in both releases | Programs | Previous preparation CPU | Updated preparation CPU | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Archived, authored form | 32 | 46.78 ms | 36.76 ms | 21.4% |
| Archived, previous round's record shorthand | 32 | 59.50 ms | 43.54 ms | 26.8% |
| Tooling, authored form | 17 | 96.46 ms | 79.87 ms | 17.2% |
| Tooling, previous round's record shorthand | 17 | 200.23 ms | 142.27 ms | 28.9% |
| Examples | 7 | 3.05 ms | 2.65 ms | 13.1% |

Each cell sums per-program medians for in-memory preparation. Four strategies ran in shuffled order for 13 measured rounds after two warmups. Holding the updated helper-binding backend fixed, changing the translator alone reduced CPU by 14.4% and 20.3% on the two shortened cohorts. A separate paired spelling comparison on the updated compiler found a median extra cost of 0.019 ms for the old record shorthand on archived scripts and 0.090 ms on tools. The first study recorded 0.680 and 2.279 ms on those cohorts in a different timing session. [Front-end experiment](frontend.py) · [Phase and paired results](results/frontend.json)

A second experiment fixed the previous translator and varied just helper discovery across 38 existing AgentLang scripts. Sum of preparation CPU medians was 48.54 ms for the previous traversal, 41.49 ms for a pruned standard-library traversal and 40.35 ms for the selected AST field traversal. A separate source-text check for completely helper-free programs helped the archived cohort but added a scan to most programs and slightly regressed the tooling cohort. We left it out. [Binding experiment](bindings.py) · [Results](results/bindings.json)

The front-end differential covered 3,402 lexical and diagnostic cases per interpreter. It also uncovered a prior bug on Python 3.12 and later. A record immediately inside an f-string replacement, such as `f"{d{score}}"`, could expand to an escaped opening brace. The compiler now preserves that expression boundary, including in Python 3.14 template strings. [Regression tests](../../tests/test_field_pass.py)

## Which pipelines got faster?

Simple literal ranking keys now compile to `operator.itemgetter`. Identity ranking needs no callback. A list-producing stage followed by `:n` can use `len`, and another `:l` can reuse the newly built list. Unknown input iterables keep their original consumption behavior. All timings below are median CPU times for 2,048 elements and exclude compilation. [Pipeline experiment](pipelines.py) · [All sizes and timing medians](results/pipelines.json)

| Pipeline suffix | Previous | Updated |
| --- | ---: | ---: |
| Sort by score, `:s _$score` | 400.4 µs | 316.0 µs |
| Select minimum by score, `:k _$score` | 152.3 µs | 73.8 µs |
| Select top six by score, `:t 6, _$score` | 164.9 µs | 114.0 µs |
| Collect and count, `:l:n` | 74.9 µs | 5.5 µs |
| Count most-common result pairs, `:c 6:n` | 193.8 µs | 196.5 µs |

Across three input sizes, 32 of 33 targeted timing cells improved. Only one of the 38 existing AgentLang scripts used an improved lowering. Its complete prepared sort, including JSON input and output, went from 6.303 to 6.022 ms on 12,288 records. Replacing optional-key callbacks with `methodcaller` slowed sorting at every tested size. More aggressive generator fusion changed error or object-lifetime behavior in counterexamples, so it was excluded. [Pipeline regression tests](../../tests/test_pipeline_lowering.py)

**Execution coverage.** Thirty-two compiled program pairs ran on 65,536 seeded fixture draws. The inputs included ties, different orderings, missing keys, empty collections, lists, tuples and one-shot iterators. All **2,097,152 program/input comparisons** agreed on result type and value or exception type and arguments on each of three Python versions. Each replay included 52,166 matching error outcomes. That is **12,582,912 old/new program executions** across three interpreters, reusing the same fixture draws. The source-spelling counts above are separate from these executions.

## Last optimization pass

The JSON/literal parser now imports `ast` only if the JSON attempt fails on a string. A clean standalone Python process reading JSON can avoid loading that module entirely. On the larger movie-credit fixture, 9,600 JSON successes and 3,200 fallback/default results gave median whole-script CPU times of 128.92 ms for the previous helper, 115.55 ms with the deferred import and 126.22 ms with an additional quote precheck. The precheck won on the tiny audit fixture. Encoding JSON before appending the newline offered no consistent advantage across payload sizes and the large fixture pack. The experiment also checked 5,128 parser inputs and 1,024 serialized values. A separate 20-pair check of a fresh standalone JSON-only program recorded 45.0 versus 37.4 ms median wall time and confirmed that only the previous program loaded the AST module on a successful JSON parse. [Codec experiment](codecs.py) · [Results and import-state probe](results/codecs.json)

We stopped at the candidates with a repeatable benefit on the selected workloads and a compatible execution path. Explicit-default lookup shorthand had zero eligible sites in the archived submissions and held-out batch. String-set shorthand appeared in tooling but had zero sites in those two application cohorts. The remaining tested parser, ranking and serialization alternatives either lost on a comparison cohort or changed observable behavior. Timings come from one shared machine and the complete-script cohorts cover a limited set of tasks.

## Reproduce from the repository root

Use this study's checkout and retain the baseline commit in local Git history. The optional benchmark dependency provides the two tokenizers. Fresh-process measurements use the repository's macOS/Linux process timer. Compare timings on an idle machine. The reference snapshots, source hashes and measured seeds are under [results](results).

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
python -m unittest discover -s tests
python -m unittest benchmarks.long.workloads.test_cases benchmarks.patterns.evaluation.test_cases
python -m benchmarks.optimization.spellings > /tmp/agentlang-spellings.json
python -m benchmarks.optimization.frontend > /tmp/agentlang-frontend.json
python -m benchmarks.optimization.bindings > /tmp/agentlang-bindings.json
python -m benchmarks.optimization.pipelines > /tmp/agentlang-pipelines.json
python -m benchmarks.optimization.codecs > /tmp/agentlang-codecs.json
python -m benchmarks.optimization.dispatch > /tmp/agentlang-dispatch.json
python -m benchmarks.scripting.launches --before 0e896bc > /tmp/agentlang-launches.json
```

To include multiple interpreters in a single pipeline report, append `--also-check /path/to/python3.10 --also-check /path/to/python3.14`. For just the deterministic pipeline replay on another interpreter, run that interpreter with `-m benchmarks.optimization.pipelines --checks-only`. The corresponding frontend command is `-m benchmarks.optimization.frontend --check-only`. Both use the standard library. On the final checkout, all applicable tests from the 47 language tests and eight workload tests passed on each interpreter. Five version-specific tests were skipped on 3.10 and two on 3.12.
