# Paired generation trials

The model writes each program from its task specification. Both arms receive the same three I/O helpers, ordinary Python control flow and access to the standard library. The compact arm also receives a description of AgentLang's pipeline and output syntax. The model may use as much ordinary Python as it chooses. The Python arm must parse as native Python before the compiler inserts shared helper definitions.

### Recorded results

| Series and arm | First passes | Visible source tokens | User prompt tokens | Service input + output | Median time through passing validation | CLI CPU total | Median CLI peak RSS per attempt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Optional, Python | 9/9 | 4,291 | 3,813 | 174,403 | 13.15 s | 10.31 s | 162.97 MiB |
| Optional, AgentLang | 9/9 | 3,822 | 5,118 | 175,161 | 11.35 s | 10.23 s | 163.81 MiB |
| Required short, Python | 6/6 | 2,637 | 2,752 | 113,940 | 12.26 s | 6.83 s | 162.73 MiB |
| Required short, AgentLang | 6/6 | 2,437 | 3,850 | 117,098 | 11.40 s | 6.76 s | 164.39 MiB |

All six required AgentLang programs used stages on task data. They filtered and extracted film crew entries, assembled training and holdout data, or expanded groups of tied scores. Of the 200 fewer source tokens in that series, 191 came from the KNN task. Across the six attempts per arm, requesting the short syntax added 1,098 user prompt tokens. The service also reported a shorter base input on one Python KNN request and different cache hit counts between arms. The measured service-token difference includes that variability.

The original series ran from approximately 2:38 to 2:42 p.m. Eastern on November 24, 2026. The second ran from approximately 2:43 to 2:46 p.m. Eastern the same day. All thirty requests returned a final program without a tool call and supplied complete usage counters.

### Protocol

The first series gives each task three rounds in both languages. It uses optional, long-form pipeline syntax. A second series runs two fresh rounds per task. It preloads `r`, `c`, and `wj` I/O aliases in **both** arms and requires the AgentLang program to use at least one one-letter collection stage on task data. Both arms receive identical helper interfaces. The [short-language reference](short-grammar.txt) goes only to AgentLang requests. The compiler counts recognized stages. A missing stage triggers the same retry policy as a failed correctness check. Accepted source is available to inspect whether each stage operates on relevant task data. The ordinary Python controls are fresh requests in each series. Compare arms within each series; the two series took place at different times with different prompts and syntax requirements.

In the optional series, all eighteen programs passed on their first attempt. None of the nine programs from the AgentLang arm used a language-specific construct. Its timing and token observations describe variation in the generated Python programs. The second series tests actual use of the short syntax.

The collector runs one request at a time, rotates task order between rounds and alternates the language tested first. It uses a fresh, empty directory and an ephemeral, read-only Codex session for every attempt. The model receives the same no-tool, source-only instructions on every request. It does not see fixture contents or correct answers. With an odd round count, one language starts twice for a given task and the other starts once.

The collector checks each candidate on three independently prepared inputs (`base`, `edges`, `profile`). A passing output is one JSON value matching the reference object. Dictionary order and formatting are insignificant, list order matters, and Boolean values are distinct from numbers. A failed check supplies only the fixture label and mismatch category, or a syntax line or exception class. The next attempt receives the original instructions, previous source and feedback in a new session. Two repairs are allowed. Each model request has a 90-second limit and each whole trial a 180-second budget. Each candidate gets up to 8 seconds of execution per case. During the trial, numeric values compare by value (an integral float can equal an integer). The separate strict replay checks expected scalar types, duplicate object keys, and an `audit` input withheld from this loop.

A trial's elapsed time starts before the first request and ends when all three correctness checks pass or the retry or time budget is exhausted. It includes CLI startup, model generation, network waits, candidate preparation, fixture creation, validation and any retries. Model-request time is also available separately. Every candidate runs in a temporary fixture directory with a minimal environment. The recorded macOS runs disable candidate network access and restrict writes to that directory.

### Measurements and artifacts

The [optional syntax trials](observations/results.json) and [required short syntax trials](required/results.json) contain verdicts, exact source filenames, generation and validation times, visible source and user prompt counts, service usage and CLI resource measurements. Identical candidate sources share one file within each series ([optional sources](observations/sources/), [required sources](required/sources/)). Every response and retry counts toward the totals, even if no program passes. If a client times out without a completed turn, the report flags its service-token usage as unknown. Client CPU time and peak resident memory come from the operating system's `wait4` accounting for each CLI command. The RSS figure is a process high-water mark. It does not measure aggregate server memory, GPU utilization, or electrical energy.

Source and user prompt tokens use the `o200k_base` tokenizer. The service reports full input, its cached portion, output, and its reasoning portion. The full input includes the Codex CLI's instructions. Raw input and output totals can be summed without counting the cached or reasoning portions again. Caching and server load are uncontrolled. All timing comparisons apply to this machine, account, model, task set and sampling run.

### Reproduce the run

Use an authenticated Codex CLI and a Python environment with `tiktoken`. From the repository root, choose a fresh output directory. A full rerun requests real model inference through the signed-in account.

```sh
python3 benchmarks/long/generation/run.py --out /tmp/agentlang-long-run --rounds 3
python3 benchmarks/long/generation/summarize.py /tmp/agentlang-long-run/results.json
python3 benchmarks/long/generation/run.py --require-pipeline --rounds 2 --out /tmp/agentlang-short-run
python3 benchmarks/long/generation/summarize.py /tmp/agentlang-short-run/results.json
```

To inspect the bundled run without making requests, substitute `benchmarks/long/generation/observations/results.json` in the summary command. [Task specifications and fixtures](../workloads/cases.py) and [exact prompt construction](run.py) reproduce the prompts, including retry feedback and previous source. Match each task specification to the SHA-256 digest in the results file before interpreting a rerun. The CLI and tokenizer versions, model identifier, reasoning effort, platform, limits, and Python version are recorded there.
