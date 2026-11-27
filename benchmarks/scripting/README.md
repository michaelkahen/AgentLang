# Scripting efficiency study

**November 27, 2026** · Baseline commit `8a5b5c5` · CPython 3.12.4 on Apple M1

AgentLang now supports `row?key` for a literal-key `.get()` call and `d{tag,count=len(rows)}` for a record containing both a local variable and a computed value. Using both was the shortest combination tested on two tokenizers, tied with a longer spelling for optional lookup. On complete programs the benefit depended on the job. Optional lookup saved more tokens in the archived submissions. Computed records saved more in the repository's own tools. [Language reference](../../docs/language.md) · [Executable example](../../examples/terse/order_summary.ag)

The largest speed gain came from CSV loading. Three prepared CSV scripts at two sizes used 11.9% less CPU on aggregate. Across a broader mix of 16 scripts launched from the command line, median paired CPU time was within 0.04% of the previous release on both fixture sizes. Adopting the shorter syntax also has a cost at compile time, measured below.

## What saved source tokens?

The table counts the entire source in each cohort, including programs with zero eligible edits. “Current” in the raw token results means the spelling available before this update.

| Corpus and tokenizer | Before | Lookup alone | Records alone | Both | Reduction with both |
| --- | ---: | ---: | ---: | ---: | ---: |
| 6,144 generated fragments · o200k | 247,148 | 234,849 | 243,639 | 230,839 | 6.60% |
| 6,144 generated fragments · cl100k | 245,380 | 233,092 | 242,018 | 229,218 | 6.59% |
| 76 archived submissions · o200k | 26,140 | 26,000 | 26,061 | 25,921 | 0.84% |
| 76 archived submissions · cl100k | 25,961 | 25,804 | 25,888 | 25,731 | 0.89% |
| 29 repository tools · o200k | 44,899 | 44,860 | 44,714 | 44,675 | 0.50% |
| 29 repository tools · cl100k | 44,531 | 44,482 | 44,351 | 44,302 | 0.51% |

**Generated fragments.** Twelve templates cover filtering, indexing, missing data, histograms, projections, joins, ranking, validation, summaries and three controls. Each has 512 distinct spellings drawn from a seeded combination of schemas, variable names and thresholds. Each fragment takes an injected `rows` input and produces a `result`. The baseline uses the shorter of a dictionary literal and `dict(name=value)` for each fragment and encoder, and retains the existing `d{x,y}` wherever it already applies. [Templates and inputs](simulation_cases.py)

Crossing four lookup spellings with three record forms gave 73,728 renderings per tokenizer. Both `?key` and `?.key` tied in every aggregate spelling comparison. We chose `?key` because it takes one less character and follows the existing `$key` form. With mixed records, `$?key` cost 7,168 more tokens than `?key` on each encoder. The alternative lookup spellings were counted as text. For the supported forms, 58,368 executions checked results on an empty list, a sparse singleton and a 24-row fixture. The literal and new forms also had to compile to identical Python abstract syntax trees. On both encoders, the combination shortened 4,608 fragments, tied on 1,536 and lengthened zero. The 6,144 fragments represent variations of 12 algorithms. [Experiment](simulate.py) · [All spelling totals and per-family results](results/tokens.json)

**Complete programs.** The transfer check uses earlier Python and AgentLang submissions from the pilot, long-script and pattern studies. Deduplicating 78 submissions by source hash left 76. The same rewrite rules also ran on 29 Python benchmark tools, including process launchers, data collection, plotting and verification. The scanner replaced eligible one-argument literal-key `.get()` calls and mixed string-key dictionary literals. It preserved the surrounding source and checked that all four variants produced the same standalone Python AST. There were 97 lookups and 13 mixed records across 32 affected submissions, and 24 lookups and 31 mixed records across 17 affected tools. This measures the opportunities captured by those specific mechanical edits. [Rewrite rules and source selection](simulation_archive.py)

**Prompt cost.** The revised short reference fits the new forms in 206 tokens on `o200k_base` and 204 on `cl100k_base`, down from 220 and 217. These are counts of the reference text itself. The study used local deterministic simulations. Model adherence, repair rate, billed service tokens and generation latency require a separate inference experiment. [Current prompt reference](../../docs/agent-reference.txt) · [Earlier live model comparison](../patterns/README.md)

## Runtime and preparation

### CSV materialization

The existing `c(path)` and `csvrows(path)` helpers still return lists of dictionaries. We compared three ways to build them. The first uses the original `csv.DictReader`. The second zips headers to values and handles missing fields in a Python loop. The selected version uses `csv.reader` and `itertools.zip_longest` to fill short rows, and stores overflow values under the same key as `DictReader`. It matched the reference, including dictionary insertion order, on 4,096 seeded files with 30,851 nonblank records. The fixtures include blank rows, duplicate headers, quoted newlines, ragged widths and Unicode. [Implementation](../../agentlang/helpers.py) · [Regression tests](../../tests/test_csvrows.py)

| Method | CPU relative to DictReader, CSV reads | CPU relative to DictReader, complete prepared scripts |
| --- | ---: | ---: |
| DictReader | 1.000 | 1.000 |
| Direct zip with explicit missing-field handling | 0.828 | 0.900 |
| **Padded zip (selected)** | **0.824** | **0.881** |

The two new readers were close on the isolated CSV matrix. Direct zip beat DictReader on 26 of 27 cells and padded zip on 25. Padded zip recorded the lowest aggregate CPU time in both comparisons and needs less code to handle short rows. The table gives the geometric mean of the per-cell median CPU ratios, weighting each cell equally. The 27 reader cells cross 8, 512 and 8,192 rows with 2, 8 and 32 columns and three data shapes. The six whole-script cells use two input sizes for each of three existing scripts. Across 11 shuffled rounds this produced 19,602 timed file reads and 1,683 timed prepared-script executions. Preparation and interpreter startup are outside these intervals. [CSV experiment](runtime.py) · [All wall and CPU samples](results/csv.json)

On scaled inputs, CPU time fell from 202.12 to 183.19 ms for movie credits, 48.00 to 36.24 ms for late flights and 47.15 to 34.60 ms for the goal-gap calculation. Five of the six whole-script cells improved. The small goal-gap script took 124.8 µs versus 96.6 µs before. Embedding the updated CSV helper adds 502 bytes to a standalone Python file that uses it.

### Compiler preparation

After expanding fields, the compiler checks for a possible stage or output command before paying for a full statement-tokenization pass. Strings and comments that resemble syntax can trigger the regular parser. A continued line also takes the regular path. The experiment compared three choices on every archived `.ag` source file and example, including the new order summary. All three produced byte-identical standalone output for each script. The timed operation was full in-memory preparation, including helper resolution and Python compilation. [Experiment](preparation.py) · [Per-script measurements](results/preparation.json)

| Statement scan | Scripts skipping a pass | Sum of median CPU times | Sum of median wall times |
| --- | ---: | ---: | ---: |
| Always scan | 0 / 38 | 136.41 ms | 255.00 ms |
| Check for a command name anywhere, or a stage | 13 / 38 | 127.03 ms | **231.83 ms** |
| Check for a command at statement start, or a stage | **14 / 38** | **125.61 ms** | 244.48 ms |

Each script had two warmups and 60 measured preparations per method, with order shuffled each round (6,840 timed preparations). The statement-start check used 7.9% less CPU in the aggregate and skipped the most scans, so it ships in both `run` and `compile`. Its median paired CPU ratio was 0.799 on the 14 scripts that skipped the pass and 1.011 on the other 24. The looser check recorded the lowest aggregate wall time on this shared host.

### Cost of choosing the shorter spelling

An existing script can gain a compiler fast path while a newly shortened one incurs extra field expansion. To measure the latter cost directly, we fed the same updated compiler both spellings of each of the 49 complete programs with eligible edits. Each pair produced an identical standalone Python AST. After two warmups, 21 randomized-order pairs per program gave 2,058 measured in-memory preparations. [Experiment](record_preparation.py) · [Per-source timings and hashes](results/record-preparation.json)

| Affected programs | Median extra preparation CPU | Median CPU ratio | Slower to prepare | Median extra wall time |
| --- | ---: | ---: | ---: | ---: |
| 32 archived submissions | +0.680 ms | 1.227× | 27 / 32 | +1.067 ms |
| 17 repository tools | +2.279 ms | 1.225× | 15 / 17 | +2.341 ms |

For a one-off script, the source-token saving comes with this preparation cost. A standalone program pays for field expansion when it is compiled. The expanded operations it executes are identical under either spelling.

### Fresh CLI launches

All 16 previously accepted AgentLang programs from the pattern study ran under both the baseline and updated public CLI. They cover a movie-credit join, a KNN grid search, fixture packaging and trace replay. Each program ran on its archived audit input and its larger profile input. Every launch had to pass the independent output oracle. One warmup per arm and eight balanced-order measured pairs per program and fixture yielded 512 timed launches and 64 warmups. Each launch used a new interpreter process, with filesystem and bytecode caches allowed to warm. [Launch experiment](launches.py) · [Individual wall and CPU samples](results/launches.json)

| Fixture | Updated / baseline wall time | Programs with lower wall time | Updated / baseline process CPU | Programs with lower CPU |
| --- | ---: | ---: | ---: | ---: |
| Audit | 0.960 | 12 / 16 | 1.000 | 8 / 16 |
| Larger profile | 0.991 | 9 / 16 | 1.000 | 8 / 16 |

For each program we divided the updated median by the baseline median, then took the median of those 16 ratios. The recorded wall-time changes were −3.96% and −0.93% respectively. Median paired CPU time was nearly flat at both sizes, and the host was under concurrent load. These runs support a speed gain for specific operations and little change in CPU use for a typical fresh launch in this mix. They used the original program text, so the release comparison includes compiler and helper changes independently of an author's decision to adopt the new spellings.

## Compatibility checks

The 32 language tests and eight workload tests passed on CPython 3.10.22, 3.12.4 and 3.14.10, with two, one and zero version-specific skips respectively. Each interpreter also matched its own `csv.DictReader` across the 4,096 generated CSV files. On all three versions, the old and new translators produced byte-identical Python and equal short-stage counts for all 37 pre-existing `.ag` files when supplied the same helper implementations. Rewriting the 16 archived pattern-study scripts touched eight. All 16 passed their original audit fixture through both the public CLI and the emitted standalone Python. [Record tests](../../tests/test_record_expressions.py) · [Workload fixtures](../patterns/evaluation/README.md)

## Reproduce

Use Python 3.10 or later. The tokenizer experiment needs the optional benchmark dependency. The spelling, record-preparation and launch comparisons read the baseline revision from local Git history. The launch benchmark uses the repository's OS-level process timer on macOS or Linux. Run the timing commands separately on an idle host for a local comparison.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
python -m unittest discover -s tests
python -m unittest benchmarks.long.workloads.test_cases benchmarks.patterns.evaluation.test_cases
python -m benchmarks.scripting.simulate --output /tmp/agentlang-tokens.json
python -m benchmarks.scripting.runtime > /tmp/agentlang-csv.json
python -m benchmarks.scripting.preparation > /tmp/agentlang-preparation.json
python -m benchmarks.scripting.record_preparation > /tmp/agentlang-record-preparation.json
python -m benchmarks.scripting.launches > /tmp/agentlang-launches.json
```

Each results file records its workload dimensions and interpreter. The token study records per-program source hashes. The launch comparison stages both packages in temporary directories and records the hashes of their source files. Seeds fix the selected cases and measurement order. Execution times vary with the interpreter, hardware and host load.
