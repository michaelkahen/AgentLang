from collections import Counter

words = (word for sentence in readjson() for word in sentence.split())
print(Counter(words).most_common(1)[0][0])
