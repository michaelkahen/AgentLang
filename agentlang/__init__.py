"""Compile AgentLang or prepare native Python with the same I/O helpers."""


def compile_source(source, filename="<agentlang>"):
    """Translate AgentLang source into standalone Python."""
    from .compiler import compile_source as translate

    return translate(source, filename)


def compile_python(source, filename="<python>"):
    """Prepare native Python with I/O helpers, preserving its Python syntax."""
    from .compiler import compile_python as prepare

    return prepare(source, filename)


def count_short_stages(source):
    """Count one-letter collection stages in an AgentLang program."""
    from .compiler import count_short_stages as count

    return count(source)
