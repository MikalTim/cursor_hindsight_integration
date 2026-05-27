"""File-based state for Cursor hooks (~/.hindsight/cursor/state/)."""

import json
import os
import re
import sys

if sys.platform != "win32":
    import fcntl
else:
    fcntl = None


def _state_dir() -> str:
    state_dir = os.path.join(os.path.expanduser("~"), ".hindsight", "cursor", "state")
    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = name.replace("..", "_")
    return (name[:200]) or "state"


def _state_file(name: str) -> str:
    safe = _safe_filename(name)
    path = os.path.join(_state_dir(), safe)
    resolved = os.path.realpath(path)
    expected_dir = os.path.realpath(_state_dir())
    if not resolved.startswith(expected_dir + os.sep) and resolved != expected_dir:
        raise ValueError(f"State file path escapes state directory: {name!r}")
    return path


def read_state(name: str, default=None):
    path = _state_file(name)
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_state(name: str, data):
    path = _state_file(name)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def increment_turn_count(session_id: str) -> int:
    lock_path = _state_file("turns.lock")
    if fcntl is not None:
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                turns = read_state("turns.json", {})
                turns[session_id] = turns.get(session_id, 0) + 1
                if len(turns) > 10000:
                    for k in sorted(turns.keys())[: len(turns) // 2]:
                        del turns[k]
                write_state("turns.json", turns)
                return turns[session_id]
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
        except OSError:
            pass

    turns = read_state("turns.json", {})
    turns[session_id] = turns.get(session_id, 0) + 1
    write_state("turns.json", turns)
    return turns[session_id]
