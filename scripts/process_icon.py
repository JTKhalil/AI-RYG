"""生成带真透明圆角的应用图标（PNG + ICO）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageChops

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "pc" / "assets"
SOURCE_CANDIDATES = [
    ASSETS / "icon_source.png",
    Path(
        r"C:\Users\clear\.cursor\projects\d-ESP32-ai\assets"
        r"\c__Users_clear_AppData_Roaming_Cursor_User_workspaceStorage_"
        r"empty-window_images_image-7a7a7b4d-0c5d-4aed-8904-a6ce0929de1c.png"
    ),
    ASSETS / "tray_icon.png",
]

CORNER_RADIUS_RATIO = 0.22
MASTER_SIZE = 512
TRAY_PNG_SIZE = 256
ICO_SIZES = (256, 128, 64, 48, 32, 16)


def _load_source() -> Image.Image:
    src = next(p for p in SOURCE_CANDIDATES if p.exists())
    return Image.open(src).convert("RGBA")


def _crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    px = img.load()
    minx, miny, maxx, maxy = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            r, g, b, _a = px[x, y]
            if r > 12 or g > 12 or b > 12:
                minx = min(minx, x)
                miny = min(miny, y)
                maxx = max(maxx, x)
                maxy = max(maxy, y)
    size = max(maxx - minx + 1, maxy - miny + 1)
    cx = (minx + maxx) // 2
    cy = (miny + maxy) // 2
    left = max(0, cx - size // 2)
    top = max(0, cy - size // 2)
    return img.crop((left, top, left + size, top + size))


def _fill_black_corners(img: Image.Image) -> Image.Image:
    w, h = img.size
    samples = []
    for y in range(int(h * 0.08), int(h * 0.18)):
        for x in range(int(w * 0.35), int(w * 0.65)):
            r, g, b, _a = img.getpixel((x, y))
            if b > r and b > 50:
                samples.append((r, g, b))
    if not samples:
        return img
    bg = tuple(sum(c[i] for c in samples) // len(samples) for i in range(3))
    work = img.copy()
    for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b, _a = work.getpixel(pt)
        if r < 30 and g < 30 and b < 30:
            ImageDraw.floodfill(work, pt, bg + (255,), thresh=35)
    return work


def _apply_round_corners(img: Image.Image, radius_ratio: float) -> Image.Image:
    w, h = img.size
    radius = max(4, int(min(w, h) * radius_ratio))
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    r, g, b, a = img.split()
    new_a = ImageChops.multiply(a, mask)
    return Image.merge("RGBA", (r, g, b, new_a))


def _prepare_square_master() -> Image.Image:
    master = _load_source()
    master = _crop_square(master)
    master = _fill_black_corners(master)
    master = master.resize((MASTER_SIZE, MASTER_SIZE), Image.Resampling.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    master.save(ASSETS / "icon_source.png", format="PNG")
    return master


def build_icons() -> None:
    master = _prepare_square_master()
    ASSETS.mkdir(parents=True, exist_ok=True)

    tray = master.resize((TRAY_PNG_SIZE, TRAY_PNG_SIZE), Image.Resampling.LANCZOS)
    tray = _apply_round_corners(tray, CORNER_RADIUS_RATIO)
    tray.save(ASSETS / "tray_icon.png", format="PNG")

    ico_images = []
    for size in ICO_SIZES:
        frame = master.resize((size, size), Image.Resampling.LANCZOS)
        ico_images.append(_apply_round_corners(frame, CORNER_RADIUS_RATIO))
    ico_images[0].save(
        ASSETS / "tray_icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=ico_images[1:],
    )

    px = tray.load()
    s = tray.size[0]
    corner_alpha = [px[(0, 0)][3], px[(5, 5)][3], px[(s - 1, 0)][3]]
    print(f"icon processed: tray={tray.size}, corner_alpha={corner_alpha}")


if __name__ == "__main__":
    build_icons()
