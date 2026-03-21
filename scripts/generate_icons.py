"""Генерация PNG-иконок PWA (192 и 512). Требуется Pillow из backend/requirements.txt."""

from pathlib import Path

from PIL import Image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    icons = root / "frontend" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    color = (35, 134, 54)
    for size in (192, 512):
        img = Image.new("RGB", (size, size), color)
        out = icons / f"icon-{size}.png"
        img.save(out)
        print("Wrote", out)


if __name__ == "__main__":
    main()
