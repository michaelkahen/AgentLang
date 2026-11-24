# Short-script pilot

The saved measurements refer to commit `b13d2e3`. The raw JSON preserves paths and hashes from that revision. The harness here also runs against the current compiler.

On four data tasks, AgentLang reduced the handwritten programs from 238 source tokens to 137. Giving plain Python the same I/O helpers reduced it to 160. In a separate live trial, the model produced 41.9% fewer source tokens and its median request finished about one second sooner. Including the language reference in every request increased total service tokens by 0.9%. [Live results and exact prompts](../generation/README.md)

## Source length

The counts use `o200k_base` on the entire UTF-8 file, including its final newline. The Python control can call the same CSV and JSON helpers as AgentLang. It uses ordinary Python for filtering, iteration, sorting, and aggregation. The generated Python column counts the complete standalone file the compiler writes locally.

| Workload | Stdlib Python | Python with I/O helpers | AgentLang | Saved vs stdlib | Generated Python |
| --- | ---: | ---: | ---: | ---: | ---: |
| Count flight complaints | 84 | 52 | 52 | 38.1% | 127 |
| Difference of project means | 80 | 59 | 52 | 35.0% | 133 |
| Most frequent word | 47 | 35 | 22 | 53.2% | 131 |
| Stable sort by score | 27 | 14 | 11 | 59.3% | 120 |
| **Total** | **238** | **160** | **137** | **42.4%** | **511** |

The Python control recovered 78 of the 101 tokens saved across the four scripts. AgentLang saved another 23 tokens, or 14.4% relative to that control. Source formatting, choice of idiom, and implicit imports are part of these totals.

## Process wall time

Cells show median milliseconds from process launch through exit, including interpreter startup. “Precompiled” means the CLI translated the program once before timing, then a fresh Python process ran the generated file on every trial. “Compile + run” includes the CLI, parsing, translation, and execution on each invocation.

| Input | Records | Stdlib Python | Python with I/O helpers | Precompiled | Compile + run |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flight complaints | 10 | 18.69 | 18.87 | 18.85 | 31.14 |
| Project means | 9 | 23.34 | 23.37 | 23.11 | 35.55 |
| Word frequency | 5 | 19.21 | 19.39 | 19.28 | 31.60 |
| Sort scores | 6 | 18.94 | 19.12 | 19.08 | 31.35 |
| Flight complaints | 10,000 | 27.98 | 28.76 | 28.61 | 41.83 |
| Project means | 9,000 | 32.47 | 32.24 | 32.30 | 43.88 |
| Word frequency | 5,000 | 20.52 | 20.58 | 20.60 | 33.16 |
| Sort scores | 6,000 | 21.82 | 21.70 | 21.36 | 34.10 |

Precompiled and ordinary Python medians were within 0.7 ms for every task and size. Translating at launch added 11.4–13.8 ms relative to ordinary Python. This includes starting the compiler CLI. The benchmark has no isolated parser timing.

## Local resource usage on the larger inputs

CPU time is the sum of user and system time for a fresh process, reported by the OS. Peak memory is its maximum resident set size. Both tables show medians. The raw data includes the same measurements for the small fixtures.

| CPU time (ms) | Stdlib Python | Python with I/O helpers | Precompiled | Compile + run |
| --- | ---: | ---: | ---: | ---: |
| Flight complaints | 25.56 | 26.34 | 26.27 | 39.14 |
| Project means | 29.97 | 29.77 | 29.80 | 41.43 |
| Word frequency | 18.90 | 18.89 | 18.94 | 31.37 |
| Sort scores | 20.09 | 19.95 | 19.75 | 32.21 |

| Peak memory (MiB) | Stdlib Python | Python with I/O helpers | Precompiled | Compile + run |
| --- | ---: | ---: | ---: | ---: |
| Flight complaints | 10.50 | 14.16 | 14.16 | 17.40 |
| Project means | 14.51 | 14.45 | 14.41 | 17.48 |
| Word frequency | 10.95 | 10.95 | 11.02 | 14.23 |
| Sort scores | 11.70 | 11.84 | 11.74 | 15.01 |

The flight filter shows a concrete tradeoff. The Python baseline streams the CSV once. The helper loads all rows into a list, which lets the project-means script iterate twice and costs an extra 3.66 MiB on the flight workload. Both control and compact programs using this helper show the increase.

## Method and limits

- The workloads adapt recorded agent operations to deterministic local inputs. Two came from notebook data analysis and two from Python tool calls on programming exercises. The examples emphasize collection processing, which the dialect was designed for. [Trace provenance and adaptations](../../../examples/PROVENANCE.md)
- The larger fixtures repeat the original records 1,000 times. They test growth in row count while preserving value distributions. Input identities, sizes, expected-output hashes, and implementation hashes accompany the raw samples.
- The host was an Apple M1 running macOS 14.8.2 and CPython 3.12.4. Each size and task had one warmup and twelve measured runs per mode. Modes were interleaved and their order rotated. OS caches could be warm. All 384 measured processes and 32 warmups exited successfully and matched expected stdout byte for byte.
- Local execution measurements use hand-authored equivalents. The live model-generation experiment measures separate requests and checks each generated program on two fixture sets. Model-serving hardware and energy data were unavailable. Server caching and the algorithms selected by the model varied between requests.
- The runtime harness used tiktoken 0.12.0, and the live harness used 0.14.0. Recounting every live source with 0.12.0 reproduced the recorded counts.

Each raw file includes individual observations, medians, quartiles, and ranges. The setup commands at the project root reproduce the two dataset sizes. [Seed measurements](results/seed.json) · [Scaled measurements](results/scaled.json) · [Setup and commands](../../../README.md)
