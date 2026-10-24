"""Which processes belong to the tool itself. Pure: process lookups are injected."""

from collections.abc import Callable, Iterable

# The tool's own helpers. Apps the guard relaunches are also its children but must stay enforced.
TOOL_NAMES = frozenset({"python.exe", "pythonw.exe", "py.exe", "pyw.exe", "msedgewebview2.exe", "conhost.exe"})


def own_tree(
    root_pid: int,
    children_of: Callable[[int], Iterable[int]],
    name_of: Callable[[int], str],
    tool_names: frozenset[str] = TOOL_NAMES,
) -> set[int]:
    found, pending = {root_pid}, [root_pid]
    while pending:
        for child in children_of(pending.pop()):
            if child not in found and name_of(child).lower() in tool_names:
                found.add(child)
                pending.append(child)
    return found


def app_tree(
    app_pid: int | None,
    alive: bool,
    children_of: Callable[[int], Iterable[int]],
    name_of: Callable[[int], str],
) -> set[int]:
    """The background app and its helper windows (notifications, errors), so a session never touches them."""
    if app_pid is None or not alive:
        return set()
    return own_tree(app_pid, children_of, name_of)
