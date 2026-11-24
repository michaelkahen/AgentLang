"""Select the client profile with the lower median service input on a trace-free neutral probe."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.patterns.generation.client import MODEL, invoke


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("choose a new output path")
    probe = "Return only the digit 4. Do not use tools."
    data = {"time_utc": datetime.now(timezone.utc).isoformat(), "model": MODEL, "prompt": probe, "observations": []}
    for profile in ("standard", "lean", "lean", "standard"):
        response, metrics, error = invoke(probe, profile, 30)
        item = {"profile": profile, "responded_four": response.strip() == "4", "error": error, **metrics}
        data["observations"].append(item)
        print(profile, item["responded_four"], item["service_usage"], flush=True)
    def typical(profile):
        samples = [x for x in data["observations"] if x["profile"] == profile]
        if any(x["error"] or not x["responded_four"] for x in samples):
            return float("inf")
        return median(x["service_usage"]["input_tokens"] for x in samples)
    standard, lean = typical("standard"), typical("lean")
    if standard == lean == float("inf"):
        raise SystemExit("Neither client profile produced two valid calibration responses.")
    data["selected_profile"] = "lean" if lean < standard else "standard"
    args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
