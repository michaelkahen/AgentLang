# Four short scripts

The initial pilot tested four single-purpose workloads. The runtime study compared hand-authored sources, including a Python control with the same I/O helpers. In the live study, the Python control used the standard library directly. The [long-script study](../long/README.md) gives the same helpers to both languages during generation.

| Artifact | Contents |
| --- | --- |
| [Process benchmark](runtime/RESULTS.md) | Source tokens, process wall time, CPU and peak memory across two input sizes |
| [Generation benchmark](generation/README.md) | Sixteen single-attempt requests, including full service usage |
| [Examples and provenance](../../examples/PROVENANCE.md) | Source traces, adaptations and fixture contracts |

Run from the repository root with the `bench` extra installed.

```sh
python benchmarks/pilot/runtime/run.py --output /tmp/agentlang-seed.json
python benchmarks/pilot/runtime/run.py --scale 1000 --output /tmp/agentlang-scaled.json
```

The published measurements used commit `b13d2e3`. The original paths in the JSON identify files at that revision.
