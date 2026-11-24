"""Plot paired differences for the one-letter benchmark. Requires matplotlib."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


HERE = Path(__file__).resolve().parent
LABELS = {"movie_credits": "Film credits", "knn_grid": "KNN search", "fixture_pack": "Fixture pack"}


def service_tokens(row):
    usage = [a["generation"]["service_usage"] for a in row["attempts"]]
    if any(u is None for u in usage):
        raise ValueError("Service tokens missing from paired trial")
    return sum(u["input_tokens"] + u["output_tokens"] for u in usage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=HERE / "generation/required/results.json")
    parser.add_argument("--output", type=Path, default=HERE / "paired-results.png")
    args = parser.parse_args()
    rows = json.loads(args.trials.read_text())["trials"]
    pairs = {}
    for row in rows:
        pairs.setdefault((row["task"], row["round"]), {})[row["arm"]] = row

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(9.25, 3.35))
    fig.subplots_adjust(left=0.155, right=0.98, top=0.72, bottom=0.19, wspace=0.38)
    fig.text(0.045, 0.91, "One-letter pipelines vs. Python with the same helpers",
             fontsize=16, weight="bold", color="#172e38")
    fig.text(0.045, 0.82, "Each point is one matched round. Positive values mean AgentLang used more.",
             fontsize=10.3, color="#435864")
    for ax, title, measure in zip(axes, ("Difference in service tokens", "Difference in time to pass (s)"),
                                   (service_tokens, lambda row: row["wall_s"])):
        values = []
        for y, task in enumerate(LABELS):
            group = [arms for (name, _), arms in sorted(pairs.items()) if name == task]
            for index, arms in enumerate(group):
                if len(arms) < 2 or not all(a["passed"] for a in arms.values()):
                    continue
                value = measure(arms["compact"]) - measure(arms["python"])
                height = y + (index - (len(group) - 1) / 2) * 0.15
                ax.plot([0, value], [height, height], lw=1.5, color="#aabec2")
                ax.scatter(value, height, s=49, color="#166d69", edgecolor="white", linewidth=0.8, zorder=3)
                values.append(value)
        extent = max([abs(v) for v in values] + [1]) * 1.18
        ax.set_xlim(-extent, extent)
        ax.set_ylim(len(LABELS) - 0.5, -0.5)
        ax.set_yticks(range(len(LABELS)), list(LABELS.values()) if ax is axes[0] else [])
        ax.set_title(title, loc="left", fontsize=11, weight="bold", pad=9)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=measure is service_tokens))
        ax.axvline(0, lw=1, color="#415560")
        ax.grid(axis="x", color="#e1e8ea", lw=0.75)
        ax.set_axisbelow(True)
        ax.spines[:].set_visible(False)
        ax.tick_params(length=0, pad=5, colors="#344957")
    fig.savefig(args.output, dpi=150, facecolor="white", metadata={"Software": "AgentLang benchmark"})
    plt.close(fig)


if __name__ == "__main__":
    main()
