"""Generate the shipped icons from the master artwork.

    assets/app_icon_source.png        ->  assets/app_icon.png  (512 px, splash)
                                          assets/app_icon.ico  (48-256 px)
    assets/app_icon_small_source.png  ->  assets/app_icon.ico  (16-32 px)

Needs Pillow (dev only, not an app dependency):  pip install Pillow
"""

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
SMALL_SIZES = (16, 24, 32)  # drawn from the simplified master


def _square(name: str) -> Image.Image:
    """Load a master, trim its transparent margin and square it, or the artwork
    floats in empty space at small sizes."""
    img = Image.open(ASSETS / name).convert("RGBA")
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop(box)
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square


def generate() -> None:
    full = _square("app_icon_source.png")
    small = _square("app_icon_small_source.png")

    full.resize((512, 512), Image.LANCZOS).save(ASSETS / "app_icon.png")
    # Pillow uses an appended image for any size it matches exactly.
    small_imgs = [small.resize((s, s), Image.LANCZOS) for s in SMALL_SIZES]
    full.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "app_icon.ico", sizes=ICO_SIZES, append_images=small_imgs)
    print(f"Wrote {ASSETS / 'app_icon.png'} and {ASSETS / 'app_icon.ico'}")


if __name__ == "__main__":
    generate()
