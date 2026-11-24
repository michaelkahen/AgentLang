"""Plot the paired tradeoff in service tokens and time to a passing result."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from summarize import HERE, metrics


SERIES = {
    "movie_credits": ("Film credits", "#197267", "o"),
    "knn_grid": ("KNN search", "#5b52a4", "s"),
    "fixture_pack": ("Fixture pack", "#a25d19", "^"),
    "replay_trace": ("Trace replay", "#356d99", "D"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=HERE / "generation/observations/results.json")
    parser.add_argument("--output", type=Path, default=HERE / "paired.png")
    args = parser.parse_args()
    pairs = {}
    for row in json.loads(args.trials.read_text())["trials"]:
        pairs.setdefault((row["task"], row["round"]), {})[row["arm"]] = metrics(row)
    fig, ax = plt.subplots(figsize=(7.6, 4.9), constrained_layout=True)
    points = []
    for task, (label, color, marker) in SERIES.items():
        series = []
        for (name, _), arms in pairs.items():
            if name != task or len(arms) != 2:
                continue
            py, ag = arms["python"], arms["compact"]
            if py["passed"] and ag["passed"] and None not in (py["total_service"], ag["total_service"]):
                series.append((ag["total_service"] - py["total_service"], ag["wall_s"] - py["wall_s"]))
        if series:
            ax.scatter(*zip(*series), s=66, marker=marker, c=color, label=label, zorder=3,
                       linewidth=0.8, edgecolor="white")
            points.extend(series)
    if not points:
        raise ValueError("No matched successful trials with complete usage")
    x, y = zip(*points)
    extent_x, extent_y = max(1, max(map(abs, x))) * 1.12, max(1, max(map(abs, y))) * 1.14
    ax.set(xlim=(-extent_x, extent_x), ylim=(-extent_y, extent_y))
    ax.fill_between([-extent_x, 0], -extent_y, 0, color="#eaf4ed", zorder=0)
    ax.axhline(0, color="#68797e", lw=1)
    ax.axvline(0, color="#68797e", lw=1)
    ax.set_title("AgentLang minus Python, one matched pair per point",
                 fontsize=14, loc="left", weight="bold", pad=12)
    ax.set_xlabel("Difference in total service tokens")
    ax.set_ylabel("Difference in time to pass (seconds)")
    ax.grid(color="#d9e1e4", linewidth=0.65, alpha=0.75)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=7, integer=True))
    ax.spines[:].set_visible(False)
    ax.tick_params(length=0, pad=5)
    ax.legend(ncol=4, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.15), fontsize=9)
    fig.savefig(args.output, dpi=150, facecolor="white", metadata={"Software": "AgentLang benchmark"})
    plt.close(fig)


if __name__ == "__main__":
    main()
