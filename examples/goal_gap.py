import csv
from statistics import mean

with open("data/projects.csv", newline="", encoding="utf-8") as file:
    projects = list(csv.DictReader(file))

def mean_goal(state):
    return mean(float(p["usd_goal_real"]) for p in projects if p["state"] == state)

print(f"{mean_goal('failed') - mean_goal('successful'):.2f}")
