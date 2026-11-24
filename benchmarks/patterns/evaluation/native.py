"""Run authored Python with the complete shared helper namespace and its native grammar."""
import os
import sys

from agentlang.helpers import SHARED_HELPERS


source = os.path.abspath(sys.argv[1])
sys.argv = [source, *sys.argv[2:]]
sys.path[0] = os.path.dirname(source)
scope = {**SHARED_HELPERS, "__name__": "__main__", "__file__": source, "__package__": None}
with open(source, "rb") as stream:
    program = compile(stream.read(), source, "exec")
exec(program, scope)
