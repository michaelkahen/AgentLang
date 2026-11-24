"""Execute native Python with the three shared I/O helpers available as globals."""

import os
import sys

from agentlang.helpers import csvrows, readjson, writejson


source = os.path.abspath(sys.argv[1])
sys.argv = [source, *sys.argv[2:]]
sys.path[0] = os.path.dirname(source)
namespace = {
    "__name__": "__main__", "__file__": source, "__package__": None,
    "csvrows": csvrows, "readjson": readjson, "writejson": writejson,
    "c": csvrows, "r": readjson, "wj": writejson,
}
with open(source, "rb") as stream:
    program = compile(stream.read(), source, "exec")
exec(program, namespace)
