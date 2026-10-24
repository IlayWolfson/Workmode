"""Held-key state for the configured emergency keys only. No hooks, no keystroke recording."""

import ctypes
from collections.abc import Iterable

_GET_STATE = ctypes.windll.user32.GetAsyncKeyState


class Win32Keys:
    def pressed(self, vks: Iterable[int]) -> set[int]:
        return {vk for vk in vks if _GET_STATE(vk) & 0x8000}
