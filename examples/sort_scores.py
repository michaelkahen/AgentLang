import json
import sys

scores = json.load(sys.stdin)
print(json.dumps(sorted(scores, key=lambda pair: pair[1])))
