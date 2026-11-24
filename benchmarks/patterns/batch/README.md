# Four scripts per request

This separate experiment measures the cost of producing four independent scripts when their specifications arrive together. Both languages get one helper card and four identical specifications. AgentLang also gets the same short syntax card as in the single-script comparison.

The fixed sequence is Python then AgentLang, followed by AgentLang then Python with the task order rotated. There are two rounds per language. A response supplies four sources, each preceded by its task name. The same compiler, model, lean client, fixtures and equality checks grade each program. Up to two repairs may request the failed programs again. The overall timer stops when all four pass or the 270-second budget expires. It includes compilation, validation and any repairs. The audit fixture is checked afterwards. A batch result is a turnaround time for all four scripts.

The raw service total includes every request and counts input plus output once. For a comparison to individual requests, use the first two fixed rounds of the single-script study, matching the number of submissions per task. Batch versus singleton comparisons also include time-of-run and model-sampling differences.

Run from the project root in the benchmark environment with the authenticated model client.

```sh
python benchmarks/patterns/batch/run.py --out /tmp/agentlang-batched-trials
```
