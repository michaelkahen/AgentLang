"""Command line entry point for the AgentLang prototype."""

import os
import sys
from types import ModuleType

from .compiler import compile_source, prepare_run


def _run_script(source, arguments):
    try:
        filename = os.path.realpath(source, strict=True)
    except OSError:
        # Retain pathlib's version-specific diagnostics for missing paths and
        # symlink loops, without importing it for a normal script launch.
        from pathlib import Path
        filename = str(Path(source).resolve())
    try:
        with open(filename, encoding="utf-8") as stream:
            code, helpers = prepare_run(stream.read(), filename)
    except (OSError, SyntaxError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    sys.argv = [filename, *arguments]
    sys.path[0] = os.path.dirname(filename)
    script = ModuleType("__main__")
    script.__file__ = filename
    sys.modules["__main__"] = script
    script.__dict__.update(helpers)
    exec(code, script.__dict__)


def main():
    argv = sys.argv[1:]
    # After an ordinary run filename all remaining tokens are script arguments.
    # Let argparse handle its option separator, dash-prefixed paths and help.
    if len(argv) >= 2 and argv[0] == "run" and not argv[1].startswith("-") and "--" not in argv:
        return _run_script(argv[1], argv[2:])

    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Compile or run compact Python pipelines")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("compile", help="emit standalone Python (stdout by default)")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path)
    run = commands.add_parser("run", help="compile and execute a source file")
    run.add_argument("source", type=Path)
    run.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_script(args.source, args.args)

    source = args.source.resolve()
    try:
        output = compile_source(source.read_text(encoding="utf-8"), str(source))
        # Validate scope errors before writing output.
        compile(output, str(source), "exec")
        if args.output is None:
            sys.stdout.write(output)
        elif args.output.resolve() == source:
            parser.error("choose an output path different from the source")
        else:
            args.output.write_text(output, encoding="utf-8")
    except (OSError, SyntaxError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
