import csv

with open("data/tweets.csv", newline="", encoding="utf-8") as file:
    tweets = csv.DictReader(file)
    count = sum(
        row["airline"] == "US Airways"
        and row["airline_sentiment"] == "negative"
        and row["negativereason"] == "Late Flight"
        for row in tweets
    )
print(count)
