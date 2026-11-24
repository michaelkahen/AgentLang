"""Command line entry point for the AgentLang prototype."""

import argparse
import sys
from pathlib import Path
from types import ModuleType

from .compiler import compile_source, prepare_run


def main():
    parser = argparse.ArgumentParser(description="Compile or run compact Python pipelines")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("compile", help="emit standalone Python (stdout by default)")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path)
    run = commands.add_parser("run", help="compile and execute a source file")
    run.add_argument("source", type=Path)
    run.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    source = args.source.resolve()
    try:
        text = source.read_text(encoding="utf-8")
        if args.command == "compile":
            output = compile_source(text, str(source))
            # Validate scope errors before writing output.
            compile(output, str(source), "exec")
            if args.output is None:
                sys.stdout.write(output)
            elif args.output.resolve() == source:
                parser.error("choose an output path different from the source")
            else:
                args.output.write_text(output, encoding="utf-8")
            return
        code, helpers = prepare_run(text, str(source))
    except (OSError, SyntaxError) as exc:
        parser.exit(1, f"{exc}\n")

    sys.argv = [str(source), *args.args]
    sys.path[0] = str(source.parent)
    script = ModuleType("__main__")
    script.__file__ = str(source)
    sys.modules["__main__"] = script
    script.__dict__.update(helpers)
    exec(code, script.__dict__)


if __name__ == "__main__":
    main()
