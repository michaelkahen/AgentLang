# Live code generation

Sixteen fresh Codex CLI requests produced one script apiece. Each of the four tasks had two Python attempts and two compact-language attempts. Each task used the same English specification in both arms. The compact arm also received a short language reference. The model saw neither the fixture contents nor the expected output.

| Measurement | Python | Compact |
| --- | ---: | ---: |
| First attempts passing both fixture sets | 8/8 | 8/8 |
| Generated source tokens, total, `o200k_base` | 616 | 358 |
| User prompt tokens, total, `o200k_base` | 818 | 2,386 |
| Full service input tokens | 148,370 | 149,938 |
| Cached input tokens, included above | 114,176 | 127,232 |
| Service output tokens, including reasoning | 648 | 436 |
| Reasoning tokens, included above | 0 | 44 |
| Median request wall time | 4.93 s | 3.91 s |
| Mean request wall time | 5.06 s | 4.26 s |
| Median local client CPU time | 1.08 s | 1.07 s |

The compact programs used 41.9% fewer source tokens. Median wall time fell 20.7%, and compact finished sooner in six of the eight matched pairs. Cache hits differed between arms. Repeating the language reference and language-specific instruction added 196 prompt tokens per request. Across these one-shot sessions the combined service input and output came to 149,018 tokens for Python and 150,374 for compact. The study used a logged-in client with a large common instruction prefix. Billing, inference-only latency, server CPU/GPU use and energy were outside the measurements.

| Task | Python source tokens, trials 1 / 2 | Compact source tokens, trials 1 / 2 | Python wall time, s | Compact wall time, s |
| --- | ---: | ---: | ---: | ---: |
| Filter flight complaints | 76 / 80 | 48 / 44 | 5.73 / 5.42 | 4.25 / 3.61 |
| Difference of project means | 160 / 161 | 63 / 130 | 6.59 / 6.75 | 4.41 / 7.11 |
| Find most frequent word | 42 / 39 | 22 / 29 | 4.44 / 3.75 | 3.67 / 3.91 |
| Sort pairs by score | 29 / 29 | 11 / 11 | 3.93 / 3.89 | 3.91 / 3.23 |

The model chose its own algorithms. Both Python attempts at the project means used exact fractions and manual rounding. One compact attempt did the same, while the other used floating-point means. Numeric edge cases beyond the tested fixtures could differ. The grammar and selected workloads favor collection pipelines. Two repeats per task on one model give a pilot measurement, with limited precision for predicting future request times.

## Reproduce

Run these commands at the repository root with Python, `tiktoken`, and an authenticated Codex CLI. Check the collected programs before executing the verification command. To recheck only the bundled trials, skip collection and pass `generation/trials.json` as the input to verification.

```sh
python3 generation/collect.py --out /tmp/agentlang-new-trials.json
python3 generation/verify.py /tmp/agentlang-new-trials.json --out /tmp/agentlang-scored.json
```

The recorded run used Codex CLI 0.170.0, tiktoken 0.14.0, model `gpt-6.2-sol`, and low reasoning effort. The collector ran one request at a time in an empty temporary directory, with ephemeral sessions, read-only access, and a no-tool instruction. All completions contained a single source response and zero tool calls. Task order rotated across rounds, and each task used both language orderings. The model and service controlled caching. Fresh executions may yield different programs and timings.

Wall time starts before CLI process launch and ends after its exit. Local CPU time includes that command's accumulated user and system time. Source lengths count the exact final response with `o200k_base`. Full service token counts come from each completed turn, including the CLI's own prompt and output framing. The collection command saves user-authored task descriptions, the common prompt, the complete compact reference, and final model sources. `collect.py`'s `make_prompt` reconstructs each exact user prompt. Session identifiers and raw transport events are omitted.

The verification command compiles compact sources and executes every program under the same Python interpreter. It checks stdout byte-for-byte on the bundled fixture and a separate fixture designed for boundary cases. The second fixtures include CSV values containing commas, a filter with zero matches, a negative difference of means, a tied mixed-case word count, and a stable sort with ties and negative scores. Each trial in `trials.json` records both verdicts.
