# Optional short syntax on four workloads

Both arms get the same task text, operators available as Python functions, aliases, standard library, model, reasoning effort, resource limits and neutral validation feedback. The Python arm emits native Python. AgentLang additionally supports three compact forms, which the model may use wherever helpful. Every trial runs in a fresh, empty working directory with a source-only instruction. The model never sees sample inputs, expected outputs or past trials. [Shared operations](operations.txt) · [AgentLang syntax](syntax.txt) · [Task specifications and deterministic fixtures](../evaluation/cases.py)

## Recorded outcome

| Measurement | Python with shared helpers | AgentLang with shared helpers |
| --- | ---: | ---: |
| Correct on first attempt and separate audit | 16/16 | 16/16 |
| Full service input + output tokens | 115,321 | 116,100 |
| Service input tokens | 109,138 | 110,050 |
| Cached input tokens, included above | 59,520 | 31,104 |
| Service output tokens, including reasoning | 6,183 | 6,050 |
| Reasoning tokens, included above | 80 | 0 |
| Visible source tokens | 6,033 | 5,986 |
| User prompt tokens | 6,740 | 7,652 |
| User prompt + visible source tokens | 12,773 | 13,638 |
| Total wall time through passing validation | 175.05 s | 170.71 s |
| Median wall time across trials | 11.28 s | 11.05 s |
| Total CLI CPU time | 10.44 s | 10.47 s |
| Median CLI peak RSS | 120.64 MiB | 122.13 MiB |

AgentLang used 779 more full-service tokens (+0.68%). Its 57 extra prompt tokens per request added 912 input tokens overall; visible programs saved 47 tokens. Cached input differed by 28,416 tokens between arms. AgentLang finished 4.34 seconds sooner across all 16 trials, driven by the KNN and fixture-pack groups. It was faster in 7 of 16 matched pairs, with a median paired difference of 0.07 seconds slower. Two pairs used fewer full-service tokens and finished sooner. None of the four task groups saved full-service tokens in aggregate.

Eleven AgentLang programs executed field lookups and ten executed record literals. Replacing just these forms with the compiler's standard Python spelling took the same programs from 5,986 to 6,179 source tokens, a 193-token saving at fixed program logic. The new extrema and top stage spellings had zero uses. Eight Python programs and ten AgentLang programs called at least one of the newly shared parsing, encoding, hashing or ranking helpers. Independent replay confirmed all 128 output checks; all 64 instrumented runs also passed.

## Frozen design

* Four paired rounds per task, sixteen pairs, thirty-two trial sequences. Three tasks come from the preceding study. The fourth processes a previously unseen event trace. Task order rotates across rounds; each task begins with Python in two pairs and AgentLang in two.
* The main measurements are full service input plus output tokens across all attempts, and wall time from the start of a trial to the first program passing the three repair fixtures. Each trial gets up to 180 seconds and three fresh CLI calls (90 seconds max each). A repair includes only the original prompt, previous program and a neutral diagnostic.
* Independent replay checks every submitted program against `base`, `edges`, `profile` and a separate `audit` case. The audit result never affects the model's prompt, retry budget or stopping rule. The original collector uses the same strict JSON checker for both arms. Time to pass the three visible-to-the-validator fixtures and subsequent audit acceptance are reported separately.
* Each attempted source and exact request receives a content hash. The manifest stores per-attempt visible source tokens, user prompt tokens, service input, cached input, output, and reasoning. Cached input and reasoning are included in the corresponding totals. CLI CPU and peak RSS measure local client resources. The service does not expose its host CPU, GPU memory or energy through this interface.
* The full schedule and first-prompt hashes are persisted before the first measured call. This is a fixed sample, without stopping based on interim results. A missing response or usage record remains in the denominator. Missing service-token counters are unknown. The observed service input minus the locally tokenized user prompt is an approximate wrapper size; the underlying tokenizer can differ from `o200k_base`.
* Wall time includes startup, service latency, network, local compilation, fixture generation, test execution and repairs. The collector checkpoints after each completed trial, archives each distinct source once per arm, and excludes post-pass archive and audit time.

## Client calibration

A neutral four-call calibration ran before workload inference. The `standard, lean, lean, standard` order compared the previous client configuration to a source-only instruction file with unused shell, view-image, computer-use, plugin, app and web-search tools disabled. Both profiles used the same signed-in Codex CLI, ephemeral read-only sessions, no approvals, `gpt-6.2-sol` and low reasoning effort. Each returned exactly the digit requested. The selected configuration was the successful one with the lower median service input. Median input fell from 18,453 to 6,412 tokens. Both measured arms used this lean configuration. The four calibration requests are separately recorded and excluded from the workload totals. [Raw calibration](calibration.json) · [CLI flags](client.py) · [Codex config reference](https://developers.openai.com/codex/config-reference)

## Reproduce

Run from the repository root on macOS or Linux using Python with `tiktoken` installed and an authenticated Codex CLI. Per-process accounting uses POSIX `wait4`. The recorded macOS run also disables network access for generated programs and limits their writes to each temporary fixture directory. Rerunning collection sends real model requests. The fixed calibration result selects the shared client profile. A separate calibration can be recorded using `calibrate.py --out /tmp/new-calibration.json`.

```sh
python3 benchmarks/patterns/generation/run.py --out /tmp/agentlang-pattern-run
python3 benchmarks/patterns/generation/verify.py /tmp/agentlang-pattern-run/results.json --out /tmp/agentlang-pattern-run/audit.json
python3 benchmarks/patterns/generation/features.py /tmp/agentlang-pattern-run/results.json --out /tmp/agentlang-pattern-run/features.json
python3 benchmarks/long/generation/summarize.py /tmp/agentlang-pattern-run/results.json
```

The [per-attempt records](observations/results.json), [generated sources](observations/sources/) and [independent audit](observations/audit.json) retain the evidence for the published run. The verification command checks schedule completeness, request and source hashes, and local prompt/source token counts before checking output correctness.

## Feature adoption

[Per-candidate feature observations](observations/features.json) distinguish submitted syntax from operations exercised on actual data. Token scanning excludes string contents and comments. For a candidate stage that could also be a Python slice or dictionary colon, the audit substitutes its long spelling and requires matching compiled syntax trees and a decrease of exactly one recognized short stage. Calls such as `obj.get(...)` continue to be ordinary Python. The lexical helper-name counts are a spelling inventory and may include an identically named local function. The dynamic counters identify the actual implementation.

A separate replay instruments each shared helper definition and the new field reads, record literals and extrema/top stage operations, then checks output against the original expected JSON on both `base` and `edges`. This confirms which operations execute when a short local name shadows a preloaded helper. Calls routed through a stage also count toward the corresponding helper when they execute that implementation. A zero dynamic count means that the two replay inputs did not exercise the operation. These replays take place outside the timed trials.
