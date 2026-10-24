"""Key names and chords used by the emergency shortcuts (Windows virtual-key codes)."""

VK = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12, "pageup": 0x21, "pagedown": 0x22, "del": 0x2E}
VK.update({chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)})
VK.update({str(digit): 0x30 + digit for digit in range(10)})
VK.update({f"f{number}": 0x6F + number for number in range(1, 13)})


def parse_chord(text: str) -> tuple[int, ...]:
    parts = [part.strip().lower() for part in text.split("+")]
    if any(not part for part in parts):
        raise ValueError(f"bad key chord: {text!r}")
    unknown = [part for part in parts if part not in VK]
    if unknown:
        raise ValueError(f"unknown key name(s) {unknown} in {text!r}")
    if len(set(parts)) != len(parts):
        raise ValueError(f"repeated key in {text!r}")
    return tuple(VK[part] for part in parts)
