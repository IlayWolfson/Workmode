"""Turn the user's picture into a multi-size .ico (centered square crop)."""

from pathlib import Path

SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def square_box(width: int, height: int) -> tuple[int, int, int, int]:
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return (left, top, left + side, top + side)


def make_icon(source: str | Path, target: str | Path) -> None:
    from PIL import Image

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        square = image.convert("RGBA").crop(square_box(*image.size))
        square.save(target, format="ICO", sizes=SIZES)
