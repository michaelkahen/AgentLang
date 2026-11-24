# Four scripts per request

This separate experiment measures the cost of producing four independent scripts when their specifications arrive together. Both languages get one helper card and four identical specifications. AgentLang also gets the same short syntax card as in the single-script comparison.

The fixed sequence is Python then AgentLang, followed by AgentLang then Python with the task order rotated. There are two rounds per language. A response supplies four sources, each preceded by its task name. The same compiler, model, lean client, fixtures and equality checks grade each program. Up to two repairs request outstanding programs. Missing or duplicate program delimiters invalidate that response for all outstanding programs. Collection stops when all four pass, the three-call limit is reached or the 270-second budget expires. The timer includes response archiving, token counting, compilation, validation and any repairs. The audit fixture is checked afterwards. A batch result is a turnaround time for all four scripts.

Visible response counts include the program-name headers. All eight accepted scripts in the batch AgentLang arm used native Python syntax. Each produced the same prepared AST under both compilers and passed all four fixtures as native Python with the shared helpers. Batch timing therefore includes a language-prompt and sampling effect. It gives no direct measurement of special syntax in use. [Per-program checks](observations/verification.json)

The raw service total includes every request and counts input plus output once. For a comparison to individual requests, use the first two fixed rounds of the single-script study, matching the number of submissions per task. Batch versus singleton comparisons also include time-of-run and model-sampling differences.

The recorded run used CPython 3.12.4, Codex CLI 0.170.0, and `o200k_base` via tiktoken 0.12.0. The singleton collector used tiktoken 0.14.0 for local source and prompt counts. Service usage comes directly from the same model client in both experiments.

Run from the project root in the benchmark environment with the authenticated model client.

```sh
python benchmarks/patterns/batch/run.py --out /tmp/agentlang-batched-trials
```

Verify the recorded schedule, reconstructed requests, exact saved responses, token counts, and accepted source programs without making a model call. The verifier replays the three grading fixtures, the independent audit, and the supplementary strict-JSON probe for trace replay. For every accepted AgentLang-arm response it also checks native Python syntax, compares both compilers’ prepared abstract syntax trees, and replays all four fixtures under the Python control when those trees match. It exits with a nonzero status if an archive check or required program verification fails.

```sh
python benchmarks/patterns/batch/verify.py benchmarks/patterns/batch/observations/results.json --out /tmp/agentlang-batch-verification.json
```
