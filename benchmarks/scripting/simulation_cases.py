"""Paired script renderings and inputs. All methods operate on the same data."""

from dataclasses import dataclass
from itertools import product
import random


# (required ID, optional number, optional flag, optional label)
SCHEMAS = (
    ("id", "cents", "paid", "region"),
    ("sku", "quantity", "available", "aisle"),
    ("station", "temperature", "online", "city"),
    ("repo", "changes", "merged", "owner"),
    ("run", "input_tokens", "finished", "model"),
    ("sensor", "reading", "calibrated", "unit"),
    ("ticket", "hours", "resolved", "team"),
    ("event_id", "duration_ms", "success", "source"),
    ("shipment", "weight_kg", "delivered", "country"),
    ("subject", "points", "passed", "course"),
    ("host", "latency", "healthy", "cluster"),
    ("account_id", "balance", "active", "currency"),
)
ROW_NAMES = ("row", "r", "record", "entry", "item", "event", "sample", "observation")
FAMILIES = ("filtered_total", "label_index", "missing_reading", "histogram",
            "projection", "join", "leaderboard", "validation_report",
            "summary", "packed_control", "required_control", "arithmetic_control")


@dataclass(frozen=True)
class Case:
    family: str
    schema: tuple
    row: str
    cutoff: int

    def inputs(self):
        ident, value, flag, label = self.schema
        rows = []
        for i in range(24):
            row = {ident: i % 13}
            if i % 4:
                row[value] = i - 3 if i % 7 else None
            if i % 5:
                row[flag] = i % 2 == 0
            if i % 3:
                row[label] = ("north", "南", "", None)[i % 4]
            rows.append(row)
        # Empty, one sparse row, and repeated IDs with mixed present/absent keys.
        return ([], rows[:1], rows)

    def source(self, get_style="method", record_style="literal"):
        """Render a script fragment with shared input 'rows' and output 'result'."""
        ident, value, flag, label = self.schema
        r, n = self.row, self.cutoff

        def lookup(field):
            suffix = {"method": f".get('{field}')", "question": f"?{field}",
                      "dollar_question": f"$?{field}", "question_dot": f"?.{field}"}
            return r + suffix[get_style]

        def record(**fields):
            if all(k == v for k, v in fields.items()):
                return "d{" + ", ".join(fields) + "}"  # already in the language
            if record_style == "mixed":
                entries = (k if k == v else f"{k}={v}" for k, v in fields.items())
                return "d{" + ", ".join(entries) + "}"
            if record_style == "keywords":
                entries = (f"{k}={v}" for k, v in fields.items())
                return "dict(" + ", ".join(entries) + ")"
            return "{" + ", ".join(f"'{k}': {v}" for k, v in fields.items()) + "}"

        key = f"{r}${ident}"
        amount, enabled, name = map(lookup, (value, flag, label))
        if self.family == "filtered_total":
            return f"result = sum(({amount} or 0) for {r} in rows if {enabled} and {key} >= {n})\n"
        if self.family == "label_index":
            return f"result = {{{key}: {name} for {r} in rows if {key} >= {n}}}\n"
        if self.family == "missing_reading":
            return f"result = next(({key} for {r} in rows if {amount} is None and {key} >= {n}), None)\n"
        if self.family == "histogram":
            return (f"result = {{}}\nfor {r} in rows:\n    label = {name}\n"
                    f"    if label and {key} >= {n}:\n        result[label] = result.get(label, 0) + 1\n")
        if self.family == "projection":
            payload = record(**{ident: ident, value: f"{amount} or 0", label: name})
            return (f"result = []\nfor {r} in rows:\n    {ident} = {key}\n"
                    f"    if {ident} >= {n}:\n        result.append({payload})\n")
        if self.family == "join":
            payload = record(**{ident: ident, label: f"labels.get({ident})", "count": f"{amount} or 0"})
            return (f"labels = {{{key}: {name} for {r} in rows if {name}}}\nresult = []\n"
                    f"for {r} in rows:\n    {ident} = {key}\n    if {ident} >= {n}:\n"
                    f"        result.append({payload})\n")
        if self.family == "leaderboard":
            payload = record(rank="rank", **{ident: key, value: amount})
            return (f"leaders = sorted(rows, key=lambda {r}: -({amount} or 0))[:{n}]\n"
                    f"result = [{payload} for rank, {r} in enumerate(leaders, 1)]\n")
        if self.family == "validation_report":
            payload = record(valid="valid", rejected="len(rows) - len(valid)", threshold=str(n))
            return f"valid = [{key} for {r} in rows if {enabled} and ({amount} or 0) >= {n}]\nresult = {payload}\n"
        if self.family == "summary":
            payload = record(total="total", count="len(rows)", above="above", threshold=str(n))
            return (f"total = sum({key} for {r} in rows)\nabove = sum({key} > {n} for {r} in rows)\n"
                    f"result = {payload}\n")
        if self.family == "packed_control":
            return (f"values = [{key} for {r} in rows if {key} > {n}]\ncount = len(values)\n"
                    f"result = {record(values='values', count='count')}\n")
        if self.family == "required_control":
            return f"result = sorted({key} for {r} in rows if {key} > {n})\n"
        if self.family == "arithmetic_control":
            return (f"numbers = [{key} for {r} in rows]\n"
                    f"result = sum({r} ** 2 for {r} in numbers if {r} % {n} == 0)\n")
        raise ValueError(self.family)


def cases(per_family, seed):
    parameters = list(product(SCHEMAS, ROW_NAMES, range(1, 17)))
    if not 1 <= per_family <= len(parameters):
        raise ValueError(f"per-family must be between 1 and {len(parameters)}")
    chosen = random.Random(seed).sample(parameters, per_family)
    for family in FAMILIES:
        for schema, row, cutoff in chosen:
            yield Case(family, schema, row, cutoff)
