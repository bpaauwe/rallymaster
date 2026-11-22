"""Builds the favicon set in ../static from checkpoint_logo_no_text.png.

    python tools/make_icons.py

The source logo is black on a transparent background. Browser tabs can be dark, so each icon puts the
logo on a white tile. At small sizes the logo's thin lines are thickened so they stay visible.
"""
import io
import os
import struct

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "static")
SOURCE = os.path.join(HERE, "checkpoint_logo_no_text.png")
BASE_STROKE = 5          # approximate line width of the circle in the source image, in pixels
SUPER = 4                # draw 4x larger, then shrink, for smooth edges


def load_logo():
    """The logo's alpha channel, cropped to the drawn part."""
    alpha = Image.open(SOURCE).convert("RGBA").getchannel("A")
    return alpha.crop(alpha.getbbox())


def make_icon(logo, size, shape="tile", fill=0.74, min_stroke=1.5):
    """shape: 'tile' = white rounded square with transparent corners, 'square' = opaque white square."""
    s = size * SUPER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shape == "tile":
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.2), fill=(255, 255, 255, 255))
    else:
        d.rectangle((0, 0, s, s), fill=(255, 255, 255, 255))
    scale = s * fill / max(logo.size)                      # fit the longer side
    grow = max(0, int(round((min_stroke * SUPER / scale - BASE_STROKE) / 2)))   # thicken thin lines
    mask = logo
    if grow:
        pad = grow * 2 + 2
        padded = Image.new("L", (logo.width + 2 * pad, logo.height + 2 * pad), 0)
        padded.paste(logo, (pad, pad))
        mask = padded.filter(ImageFilter.MaxFilter(2 * grow + 1))
        mask = mask.crop(mask.getbbox())
        scale = s * fill / max(mask.size)
    mask = mask.resize((max(1, round(mask.width * scale)), max(1, round(mask.height * scale))), Image.LANCZOS)
    black = Image.new("RGBA", mask.size, (0, 0, 0, 255))
    img.paste(black, ((s - mask.width) // 2, (s - mask.height) // 2), mask)
    return img.resize((size, size), Image.LANCZOS)


def write_ico(path, images):
    """A .ico holding several PNG-compressed sizes."""
    blobs = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        blobs.append((im.width, im.height, buf.getvalue()))
    head = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for w, h, data in blobs:
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(head + entries + b"".join(data for _, _, data in blobs))


def main():
    os.makedirs(OUT, exist_ok=True)
    logo = load_logo()
    small = {16: make_icon(logo, 16, fill=0.88, min_stroke=0.9),
             32: make_icon(logo, 32, fill=0.82, min_stroke=1.4),
             48: make_icon(logo, 48, fill=0.78, min_stroke=1.8)}
    small[16].save(os.path.join(OUT, "favicon-16x16.png"))
    small[32].save(os.path.join(OUT, "favicon-32x32.png"))
    write_ico(os.path.join(OUT, "favicon.ico"), [small[16], small[32], small[48]])
    make_icon(logo, 180, shape="square", fill=0.62, min_stroke=3).save(os.path.join(OUT, "apple-touch-icon.png"))
    make_icon(logo, 192, fill=0.7, min_stroke=3).save(os.path.join(OUT, "android-chrome-192x192.png"))
    make_icon(logo, 512, fill=0.7, min_stroke=4).save(os.path.join(OUT, "android-chrome-512x512.png"))
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
