# Token profile of the earlier long scripts

The corpus contains 30 accepted model outputs from the earlier experiments, with 15 Python and 15 AgentLang programs solving the same three tasks. Each task appears five times per language across two prompt conditions. The results weight each trial once. They describe this benchmark's movie join, classifier and fixture-packaging programs. [Free-choice trials](../../long/generation/observations/results.json) · [Required-pipeline trials](../../long/generation/required/results.json)

## Where source tokens went

| Lexical category | Python tokens | AgentLang tokens |
| --- | ---: | ---: |
| Operators and punctuation | 2,342 | 2,171 |
| Names, including attributes, helpers and stage names | 2,055 | 1,853 |
| Strings and string delimiters | 1,045 | 966 |
| Standalone layout | 738 | 634 |
| Python keywords | 605 | 519 |
| Numbers | 117 | 116 |
| Comments | 26 | 0 |
| **Total** | **6,928** | **6,259** |

The counter runs `o200k_base` once on each complete source. It maps every UTF-8 byte to its Python lexical category. Each model token goes to the category of its first byte belonging to a lexeme, or to layout when it spans only whitespace outside lexemes. Thus indentation fused with a name belongs to that name. Brackets, commas and other punctuation share the operators category. Embedded literal whitespace remains part of a string, and soft keywords follow their lexical identification as names. The seven categories add up exactly. [Complete counts](counts.json)

| Repeated native source pattern | Python sites / exclusive tokens | AgentLang sites / exclusive tokens | Workloads represented across arms |
| --- | ---: | ---: | ---: |
| Tuple, list and set literals | 124 / 743 | 114 / 577 | 3 |
| Comprehensions and generator expressions | 65 / 642 | 47 / 429 | 3 |
| Positional, dynamic or slice indexing | 125 / 464 | 112 / 416 | 3 |
| Comparisons | 85 / 365 | 70 / 305 | 3 |
| Dictionary literals | 28 / 352 | 30 / 494 | 3 |
| Loop headers | 56 / 266 | 51 / 235 | 3 |
| String-key field lookups | 69 / 246 | 66 / 233 | 2 |
| Keyed selection and sorting | 16 / 90 | 16 / 83 | 2 |
| SHA-256 and hex digest method calls | 18 / 79 | 16 / 67 | 1 |

The AST miner recognizes a fixed collection of expression and header shapes. Of the matching shapes around a token, the shortest source span owns it. Each token contributes at most once to the exclusive column. A SHA expression contributes two call sites, one hash call and one hex method. The JSON report also records total coverage *within* each family, sample source, the contributing tasks and program counts. Coverage for enclosing and enclosed families can overlap. The profiler parses original native spans, masks the previously shipped short stage/command markers with equal-width syntax, and excludes any AST pattern crossing a masked marker. Lexical accounting includes the full source. [Profiler](measure.py)

## Fixed-program opportunities

A mechanical rewriter applies the same eligibility rules to every program. It retains variable names, imports, wrapper definitions, input data and unrelated formatting, then retokenizes each complete result. It runs every distinct program variant on the original base, edge, profile and independent audit fixtures. All 30 programs passed at every step. Formatting internal to a replaced expression can change, such as a multiline dictionary becoming one packed record. The first six rows retain the original algorithms. The final two also substitute the stable heap-based top-N operation for a full sort followed by slicing. [Rewriter and fixture verification](opportunities.py) · [Per-program results and hashes](opportunities.json)

| Cumulative source form | Prior Python | Prior AgentLang | Combined |
| --- | ---: | ---: | ---: |
| As written | 6,928 | 6,259 | 13,187 |
| Use exact JSON-byte and SHA-256 helpers | 6,823 | 6,159 | 12,982 |
| Also use shared min/max helpers | 6,813 | 6,149 | 12,962 |
| Express eligible extrema with key-expression stages | 6,777 | 6,114 | 12,891 |
| Also use string-key selectors | 6,749 | 6,089 | 12,838 |
| Also pack complete named-field records | **6,713** | **6,046** | **12,759** |
| Shared helpers including heap-based top-N | 6,805 | 6,145 | 12,950 |
| Shared helpers and all syntax including heap-based top-N | 6,679 | 6,013 | 12,692 |

- Hashing and newline-terminated UTF-8 JSON serialization saved **205 tokens** across the 10 fixture-packaging programs. The recognizers matched 17 exact digest chains and 10 encoders using default JSON options. The same helpers are available in Python and AgentLang.
- Across the 20 KNN and movie programs, the rewriter found **135** identifier-shaped string-key lookups. Replacing the bracket suffix in expressions like `row["id"]` with `row$id` saved **53 whole-program tokens** at this step. Neighboring delimiters often share tokens in the original source.
- The 20 eligible extrema selections use the same minimum/maximum algorithm and key ordering. A selected expression such as `min(votes, key=lambda label: (-votes[label], label))` can become `votes:k (-votes[_], _)` at an assignment or return. Whole-program savings beyond the shared min/max helper control were **71 tokens**.
- Eleven dictionaries had all 44 fields already named for their local values, including calls such as `dict(k=k, metric=metric, weights=weights, correct=correct)`. Replacing them with packed records saved **79 tokens**. Eighteen additional mixed dictionaries had 36 matching individual fields. The implemented whole-record rule leaves them intact.
- Eight sorted slices with constant nonnegative limits qualified for heap-based top-N. These have pure, comparable keys on the task data and preserve the specified output and tie order. Their underlying selection algorithm differs. Leaving them out gives **3.25% fewer tokens** across both original arms, including **1.57%** below the equivalent shared-helper baseline. Including them gives **3.75%** below the original source.
- The historical JSON/Python-literal fallback functions use varying exception lists, strict-JSON options, whitespace handling and return contracts. The rewriter leaves them intact. Their size alone gives no measured savings for the parse helper.

The rewriter uses long helper names when a short name is already bound in the program. Selectors preserve the actual subscript base and accept only identifier-shaped string keys. Packed records require unique names and same-named local values. Filters exclude nested lambda/comprehension scopes when substituting implicit extrema variables. Counts reflect these explicit rules and their fixed application order. Source-token savings are distinct from elapsed model time and execution resources.

Run both commands from the project root with the benchmark tokenizer installed.

```sh
python benchmarks/patterns/profile/measure.py
python benchmarks/patterns/profile/opportunities.py
```
