# AgentLang benchmark reports

The two most recent studies compare releases on the same scripts and count source tokens with two tokenizers. The earlier studies also ran live model trials and recorded service token usage and time to a correct submission.

## Language and runtime updates

| Study | What changed | Report and data |
| --- | --- | --- |
| Second round · `0e896bc` → `0add247` | Faster CLI startup, record scanning and field ranking. Word lists and tuples shorten column and state declarations. | [Findings and reproduction commands](optimization/README.md) · [Measurements](optimization/results/) |
| First round · `8a5b5c5` → `0e896bc` | Optional field lookup, records with computed values and faster CSV loading. | [Findings and reproduction commands](scripting/README.md) · [Measurements](scripting/results/) |

For end-to-end speed, the launch records pair the previous and updated CLI on the same inputs. For token savings, the spelling results include complete scripts alongside generated fragments. [Per-launch samples](optimization/results/launches.json) · [Spelling comparisons](optimization/results/spellings.json)

## Earlier studies

| Question | Report |
| --- | --- |
| Where do tokens go in agent-written scripts, and how does batching affect cost? | [Pattern and batching study](patterns/README.md) |
| How do longer Python and AgentLang scripts compare on generation, correctness and execution? | [Long-script study](long/README.md) |
| How did the original four short tasks compare with Python using the same helpers? | [Short-script pilot](pilot/README.md) |
