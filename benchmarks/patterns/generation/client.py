"""Run one fresh CLI request and keep measurements without transport identifiers."""
import json
from pathlib import Path
import tempfile

from benchmarks.long.generation.run import monitored


HERE = Path(__file__).resolve().parent
MODEL = "gpt-6.2-sol"
COMMON_FLAGS = ["--no-daemon", "-a", "never", "exec", "--skip-git-repo-check", "--ephemeral",
                "--ignore-user-config", "-s", "read-only", "-c", "project_doc_max_bytes=0",
                "-c", 'model_reasoning_effort="low"']
LEAN_FLAGS = ["--disable", "shell_tool", "--disable", "view_image", "--disable", "computer_use",
              "--disable", "plugins", "--disable", "apps", "-c", 'web_search="disabled"']


def invoke(request, profile, timeout):
    args = ["codex", *COMMON_FLAGS]
    if profile == "lean":
        instructions = str(HERE / "instructions.txt")
        args.extend([*LEAN_FLAGS, "-c", f"model_instructions_file={json.dumps(instructions)}"])
    elif profile != "standard":
        raise ValueError(f"unknown client profile {profile}")
    args.extend(["-m", MODEL, "--color", "never", "--json", "-"])
    with tempfile.TemporaryDirectory() as cwd:
        data, _, metrics = monitored(args, request.encode(), cwd, timeout)
    events = []
    for line in data.splitlines():
        try:
            events.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # A timeout can leave an unfinished final event.
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    messages = [i["text"] for i in items if i.get("type") == "agent_message"]
    non_messages = [i.get("type") for i in items if i.get("type") != "agent_message"]
    usages = [e["usage"] for e in events if e.get("type") == "turn.completed" and e.get("usage")]
    metrics["service_usage"] = {
        key: sum(u.get(key, 0) for u in usages) for key in set().union(*usages)
    } if usages else None
    metrics["message_count"] = len(messages)
    metrics["non_message_items"] = non_messages
    if metrics["timed_out"]:
        error = "Generation exceeded the time limit."
    elif metrics["exit"] or not usages or not messages:
        error = "The client returned no complete program."
    elif non_messages or len(messages) != 1:
        error = "Return only one source response without tool calls."
    else:
        error = None
    return messages[-1] if messages else "", metrics, error
