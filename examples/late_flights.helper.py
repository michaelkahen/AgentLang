rows = csvrows("data/tweets.csv")
print(sum(row["airline"] == "US Airways" and row["airline_sentiment"] == "negative" and row["negativereason"] == "Late Flight" for row in rows))
