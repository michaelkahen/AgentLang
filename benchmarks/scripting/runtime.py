"""CSV materialization methods, differential cases and warm complete-script timings.

Run from the repository root:
    python3 -m benchmarks.scripting.runtime > benchmarks/scripting/results/csv.json
"""

import builtins
import contextlib
import csv
import io
import itertools
import json
import os
from pathlib import Path
import platform
import random
import statistics
import sys
import tempfile
import time

from agentlang.compiler import prepare_run
from agentlang.helpers import csvrows
from benchmarks.long.workloads.cases import matches, prepare
from benchmarks.pilot.runtime.scale import prepare_examples

ROOT = Path(__file__).resolve().parents[2]
SEED = 731509
ROUNDS = 11
FUZZ_CASES = 4096


def dict_reader(path):
    """Pre-update implementation."""
    import csv

    with builtins.open(path, encoding="utf-8", newline="") as stream:
        return builtins.list(csv.DictReader(stream))


def direct_zip_reader(path):
    """Zip the fields first, then repair shape differences in each record."""
    import csv

    with builtins.open(path, encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        fields = builtins.next(reader, [])
        width = builtins.len(fields)
        result = []
        for row in reader:
            if not row:
                continue
            record = builtins.dict(builtins.zip(fields, row))
            size = builtins.len(row)
            # Match DictReader's defaults for ragged records and duplicate headers.
            if size < width:
                for field in fields[size:]:
                    record[field] = None
            elif size > width:
                record[None] = row[width:]
            result.append(record)
        return result


METHODS = {"DictReader": dict_reader, "zip_longest": csvrows, "direct_zip": direct_zip_reader}
CELLS = ["", "text", "a,b", 'a"b', "many\r\nlines", "β", "é", "\t", "123"]


def write_csv(path, records):
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(records)


def differential(path):
    rng = random.Random(SEED)
    total_rows = 0
    for trial in range(FUZZ_CASES):
        width = rng.randrange(10)
        records = [rng.choices(CELLS, k=width)]
        for _ in range(rng.randrange(18)):
            records.append(rng.choices(CELLS, k=rng.randrange(width + 6)))
        write_csv(path, records)
        expected = [list(record.items()) for record in dict_reader(path)]
        total_rows += len(expected)
        for method, reader in METHODS.items():
            actual = [list(record.items()) for record in reader(path)]
            if actual != expected:
                raise AssertionError((trial, method, records, actual, expected))
    return {"files": FUZZ_CASES, "nonblank_data_records": total_rows}


def measure(functions, iterations, rng):
    for function in functions.values():
        function()
    wall = {name: [] for name in functions}
    cpu = {name: [] for name in functions}
    order = list(functions)
    for _ in range(ROUNDS):
        rng.shuffle(order)
        for name in order:
            call = functions[name]
            wall_start = time.perf_counter_ns()
            cpu_start = time.process_time_ns()
            for _ in range(iterations):
                call()
            cpu[name].append(round((time.process_time_ns() - cpu_start) / (iterations * 1000), 3))
            wall[name].append(round((time.perf_counter_ns() - wall_start) / (iterations * 1000), 3))
    return {"iterations_per_sample": iterations, "wall_us": wall, "cpu_us": cpu,
            "median_wall_us": {k: statistics.median(v) for k, v in wall.items()},
            "median_cpu_us": {k: statistics.median(v) for k, v in cpu.items()}}


def matrix(path, rng):
    cells = []
    for count, width, shape in itertools.product((8, 512, 8192), (2, 8, 32), ("regular", "ragged", "quoted")):
        rows = [[f"column_{col}" for col in range(width)]]
        data_rng = random.Random(SEED + count + width)
        for row in range(count):
            length = width + data_rng.randrange(-2, 3) if shape == "ragged" else width
            fields = (data_rng.choices(CELLS, k=length) if shape == "quoted"
                      else [str(row + col) for col in range(length)])
            rows.append(fields)
        write_csv(path, rows)
        expected = dict_reader(path)
        methods = {}
        for name, reader in METHODS.items():
            if reader(path) != expected:
                raise AssertionError((name, count, width, shape))
            methods[name] = lambda reader=reader: reader(path)
        cells.append({"records": count, "columns": width, "shape": shape,
                      **measure(methods, max(1, 512 // count), rng)})
    return cells


def full_scripts(directory, rng):
    scripts = []
    archived = ROOT / "benchmarks/patterns/generation/observations/sources/movie_credits-compact-r1-a1.ag"
    for task, path in [("movie_credits", archived), ("late_flights", ROOT / "examples/late_flights.ag"),
                       ("goal_gap", ROOT / "examples/goal_gap.ag")]:
        code, bindings = prepare_run(path.read_text(), str(path))
        for variant in ("base", "profile"):
            folder = directory / task / variant
            if task == "movie_credits":
                fixture = prepare(task, variant, folder)
                dimensions = fixture["dimensions"]
            else:
                folder, fixtures = prepare_examples(ROOT / "examples", folder,
                                                    1 if variant == "base" else 2048, [task])
                dimensions = fixtures[task]

            def run(reader):
                namespace = dict(bindings, c=reader, csvrows=reader, __name__="__main__")
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    exec(code, namespace)
                return buf.getvalue()

            previous = os.getcwd()
            os.chdir(folder)
            try:
                methods = {}
                for name, reader in METHODS.items():
                    result = run(reader)
                    if task == "movie_credits":
                        passed = matches(result, fixture["expected"])
                    else:
                        passed = result == (folder / f"{task}.out").read_text()
                    if not passed:
                        raise AssertionError((task, variant, name, result))
                    methods[name] = lambda reader=reader: run(reader)
                scripts.append({"task": task, "fixture": variant, "dimensions": dimensions,
                                **measure(methods, 16 if variant == "base" else 1, rng)})
            finally:
                os.chdir(previous)
    return scripts


def main():
    rng = random.Random(SEED)
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        path = directory / "input.csv"
        report = {"python": sys.version.split()[0], "platform": platform.platform(),
                  "shipped_method": "zip_longest",
                  "seed": SEED, "rounds": ROUNDS, "differential": differential(path),
                  "csv_matrix": matrix(path, rng), "prepared_scripts": full_scripts(directory, rng)}
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
