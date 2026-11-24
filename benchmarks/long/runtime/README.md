# Runtime of generated programs

The benchmark measures the first accepted source in each task, generation round, and language. A runtime comparison requires both languages to have an accepted answer in the same task and round. Both accepted sources must also pass an unseen audit fixture. The audit happens after generation and supplies no feedback to the model. The results retain excluded pairs and the attempt number of each selected source.

## Larger-input results

All 15 matched program pairs passed their audit and produced the expected result on every timed run. The two series yielded 768 measured process launches on an Apple M1 running macOS 14.8.2 and CPython 3.12.4.

Each cell gives **wall ms / CPU ms / peak MiB**. Values are the median of each generated program's medians, giving each of the three free-choice or two required-short program pairs equal weight per task.

| Series | Task | Python, fresh | AgentLang, fresh | Python, prepared | AgentLang, prepared |
| --- | --- | ---: | ---: | ---: | ---: |
| Free choice | Movie credits | 100.5 / 97.3 / 17.5 | 106.1 / 103.1 / 18.8 | 98.5 / 95.7 / 17.8 | 99.1 / 96.2 / 17.9 |
| Free choice | KNN grid | 44.0 / 41.8 / 13.4 | 50.2 / 48.1 / 15.3 | 42.8 / 40.7 / 13.1 | 41.7 / 39.5 / 13.0 |
| Free choice | Fixture pack | 94.3 / 91.6 / 27.1 | 104.0 / 101.3 / 30.1 | 92.1 / 89.6 / 28.1 | 94.3 / 91.6 / 28.3 |
| Short required | Movie credits | 90.8 / 88.4 / 17.4 | 106.4 / 104.1 / 18.5 | 91.7 / 89.4 / 17.4 | 98.8 / 96.6 / 17.6 |
| Short required | KNN grid | 65.9 / 63.8 / 13.5 | 110.2 / 107.9 / 15.0 | 65.1 / 62.9 / 13.0 | 99.8 / 97.6 / 12.7 |
| Short required | Fixture pack | 96.3 / 93.7 / 27.4 | 105.0 / 102.2 / 30.6 | 94.0 / 91.2 / 26.7 | 96.6 / 94.0 / 27.9 |

The two most divergent prepared KNN pairs went in opposite directions. Free-choice round 1 took 92.1 ms in Python and 44.8 ms in AgentLang. Its AgentLang-arm implementation cached each point’s top five neighbors for reuse across the parameter grid. Its Python counterpart reranked neighbors for every configuration. Required-short round 1 took 41.5 ms in Python and 107.7 ms in AgentLang. The samples compare independently authored programs, so their algorithms affect execution time. [Free-choice Python](../generation/observations/sources/knn_grid-python-r1-a1.py) · [Free-choice AgentLang](../generation/observations/sources/knn_grid-compact-r1-a1.ag)

| Profile workload | Input files | Stdin | Stdout |
| --- | ---: | ---: | ---: |
| Movie credits, 8,000 movie rows and 8,000 credits rows | 600,438 B | 0 B | 291 B |
| KNN grid, 210 training rows and 30 test rows | 2,913 B | 0 B | 1,176 B |
| Fixture pack, 230,528 expanded records | 91,830 B | 3 B | 881 B |

The fixture-pack script computed checksums over 4,822,463 bytes of expanded input data and emitted the checksum report. Post-run snapshots recorded zero new or modified files in the working directories across all 768 measurements.

## Reproduce

Run the harness from the repository root on macOS or Linux.

```sh
python3 benchmarks/long/runtime/run.py --runs 8 --seed 42 --output /tmp/agentlang-runtime.json
python3 benchmarks/long/runtime/run.py --runs 4 --seed 42 \
  --trials benchmarks/long/generation/required/results.json --output /tmp/agentlang-required.json
```

The harness uses the project's compiler and the standard library. It generates each workload locally, then checks stdout against an independent JSON oracle on every warmup and measured run. [Free-choice model outputs](../generation/observations/results.json) · [Required-pipeline model outputs](../generation/required/results.json) · [Workload definitions](../workloads/cases.py)

## Execution modes

| Mode | Executed process |
| --- | --- |
| Python, fresh | CPython runs a small native launcher, supplies the three shared I/O helpers as globals, and compiles and executes the authored source with Python's own compiler. |
| AgentLang, fresh | The public `python -m agentlang run` CLI translates and executes the authored source in a fresh interpreter. |
| Python, prepared | The harness inserts any needed I/O helper definitions once before measurement. CPython directly executes the resulting script. Python syntax keeps its native meaning. |
| AgentLang, prepared | The harness translates the source once before measurement. CPython directly executes the resulting standalone script. |

Fresh runs include each launcher's startup costs. Prepared runs include interpreter startup and Python compilation of the prepared text. All four modes use a fresh process per sample. The data mark candidates whose prepared bytes equal their authored bytes. For those Python candidates, the prepared measurement also gives direct execution of the unmodified source. Each receives an identical new copy of its fixture directory, keeping copy costs outside the timer and allowing the OS file cache to stay warm.

## Reading the measurements

Each accepted pair runs on both the base and larger profile inputs. Each size gets one warmup per mode, then eight measured runs in the free-choice series or four in the required-pipeline series. The harness interleaves the four modes and rotates their positions, using the recorded seed to shuffle the order between blocks. OS `wait4` provides per-child user and system CPU, peak resident memory, page faults, and block I/O operation counts. Wall time spans process launch through exit. JSON verification happens after the timer stops.

The [free-choice data](results.json) and [required-pipeline data](required.json) give input file sizes, hashes, stdin bytes supplied, source bytes, stdout/stderr bytes produced, and each individual resource measurement. File sizes describe the workload available to the script. The results also record the number and final size of new or modified files left in each working directory, using file size and modification time to detect changes after exit. OS block counters reflect I/O operations observed by the kernel. Memory uses MiB (1,048,576 bytes). Five-number summaries give minimum, lower quartile, median, upper quartile, and maximum.
