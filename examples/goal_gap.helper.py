from statistics import mean

projects = csvrows("data/projects.csv")

def mean_goal(state):
    return mean(float(p["usd_goal_real"]) for p in projects if p["state"] == state)

print(f"{mean_goal('failed') - mean_goal('successful'):.2f}")
