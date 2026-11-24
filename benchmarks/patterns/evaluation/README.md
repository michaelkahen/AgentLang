# Independent workload and process measurements

Four tasks share the same fixtures and expected results between Python and AgentLang. The movie join, KNN search, and fixture packaging reuse the earlier suite. The fourth task tests reconstruction of agent event streams. Its contract and expected outcomes were fixed before inspecting the mined operations.

## Held-out task

The earlier agent-authored generation collector parses JSON Lines, tolerates a truncated last event, identifies completed messages, and collects usage from completed turns. The held-out workload adapts this operation to interleaved runs with duplicates, out-of-order events, failures, and unfinished runs. The run and sequence envelope, inputs, and exact recovery requirements are synthetic benchmark additions. The frozen prompt has SHA-256 `808b406ddfa1c0235267017af04724a4370f5ca62b09488c81c5f4152bb0b37d`. [Original collector at 934d61a](../../../benchmarks/long/generation/run.py#L103-L113) · [Contract and fixture generator](cases.py)

The generator constructs known run histories before it shuffles and corrupts the wire data. On the large input, 1,200 distinct runs produce 8,003 lines and 767,847 bytes. The report must reconstruct 400 successful, 400 failed, and 400 open runs, 1,600 commands, 3,114,200 input tokens, and 239,400 output tokens. These counts are fixture data. The small and audit variants use hand-specified answers, including duplicate sequence numbers, invalid payloads, Unicode, and messages after a terminal event.

The preexisting strict JSON checker verifies exact scalar types and all contents, accepts equivalent formatting and object-key order, and rejects duplicate keys and extra output. A regression test hashes every original base, audit, and profile input and expected answer and compares them to the saved earlier experiment. [Fixture checks](test_cases.py)

The supplementary strict-JSON probe was added after the four fixtures froze and before inspecting candidate programs. A single-quoted Python literal represents an otherwise valid event, followed by a genuine JSON event. Only the latter belongs in the output. This checks a potential difference between strict JSON decoding and a helper that also accepts Python literals. It supplies no feedback and has no effect on the prespecified timing cohort. [Probe input](strict-json.jsonl)

## Process results

All 16 matched pairs passed the unseen audit and every timed run on the profile input. All eight accepted trace-replay programs also passed the supplementary strict-JSON probe. The 512 process measurements ran on an Apple M1 with macOS 14.8.2 and CPython 3.12.4, after both inference experiments, using compiler commit `0929af2`.

Each cell shows **wall ms / CPU ms / peak resident MiB**. It gives the median across the four independently generated programs’ individual medians for each task and language.

| Task | Python, fresh | AgentLang, fresh | Python, prepared | AgentLang, prepared |
| --- | ---: | ---: | ---: | ---: |
| Movie credits | 85.9 / 83.5 / 16.8 | 92.3 / 89.8 / 18.4 | 85.9 / 83.5 / 17.0 | 86.0 / 83.6 / 17.0 |
| KNN grid | 86.1 / 83.7 / 12.8 | 100.3 / 98.1 / 14.6 | 85.1 / 82.6 / 12.4 | 91.5 / 89.4 / 12.6 |
| Fixture pack | 88.0 / 85.5 / 24.3 | 95.9 / 92.9 / 26.6 | 86.8 / 84.3 / 23.9 | 86.6 / 84.1 / 24.4 |
| Held-out trace replay | 46.0 / 43.4 / 17.5 | 59.3 / 56.8 / 19.4 | 45.0 / 42.5 / 17.3 | 50.0 / 47.5 / 17.3 |

Across the 16 paired samples, the median AgentLang/Python ratio for fresh wall time was 1.092. The median paired difference was +7.69 ms, with one AgentLang program faster. Prepared wall time had a median paired ratio of 0.9998 and a median difference of −0.02 ms, with eight AgentLang programs faster. The trace-replay programs received a 767,847-byte file, emitted 158,361 bytes of JSON on stdout, and left zero new or modified files. Program choices and interpreter startup both contribute to these measurements. The raw records give every timed observation, separate user/system CPU, page faults, OS block I/O operations, fixture and stream byte counts, and file changes at exit. [Resource measurements](runtime.json)

### Fixed-source compiler comparison

The same six archived, previously accepted AgentLang programs were checked against their original audit using two execution paths. The harness then timed the current compiler's direct in-memory preparation and its previous strategy of emitting standalone Python and compiling the emitted text. For each source the two paths alternated order over two warmups and 20 measured repetitions per path in a single Python process. File reads, process startup and execution of the candidate program were outside the interval.

The median of the six per-source medians was **1.085 ms direct** and **1.172 ms via emitted Python**, a difference of 0.087 ms (7.4%). The direct path had a lower median for all six sources. This is a preparation-time result using the current compiler implementation for both paths. [Preparation measurements](compile-paths.json) · [Measurement script](compile_paths.py)

## Reproduction

Run from the repository root on macOS or Linux with Python 3.10 or newer.

```sh
python3 -m unittest benchmarks.patterns.evaluation.test_cases
python3 benchmarks/patterns/evaluation/profile.py --runs 8 --seed 42 --output /tmp/agentlang-pattern-profile.json
python3 benchmarks/patterns/evaluation/compile_paths.py /tmp/agentlang-compile-paths.json
```

The resource benchmark selects the first accepted attempt in each arm and generation round. It runs both candidates against the unseen audit before timing either one. A missing candidate or an audit failure excludes the pair from the paired timing table and remains visible in the raw report. Each surviving pair gets one warmup and eight measured runs with four interleaved modes on the large input. Every output must match its independent oracle.

Fresh Python runs the authored program using native CPython syntax and the exact shared helper callables as globals. Fresh AgentLang uses its public CLI. Prepared runs invoke CPython directly on each arm's pre-expanded standalone program, with preparation outside the clock. The harness reuses the earlier OS-level timing code and balanced per-round order. File setup and JSON grading happen outside the measured interval. The hardware's file cache may be warm. [Harness](profile.py) · [Process measurement](../../long/runtime/run.py)
