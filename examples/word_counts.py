import json
import sys
from collections import Counter

sentences = json.load(sys.stdin)
words = (word for sentence in sentences for word in sentence.split())
print(Counter(words).most_common(1)[0][0])
