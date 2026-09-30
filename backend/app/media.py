"""Image uploads: decode with Pillow, reject non-images, strip metadata, resize to
≤ 1920 px and re-encode to WebP, so no uploaded file is ever served as-is."""

import io
import os
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5_000_000
MAX_SIDE = 1920
ALLOWED = {"PNG", "JPEG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard


class BadImage(ValueError):
    pass


def process_image(data: bytes) -> tuple[bytes, int, int]:
    if len(data) > MAX_BYTES:
        raise BadImage("Image is over 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED:
            raise BadImage("Use PNG, JPEG, WebP or GIF")
        with Image.open(io.BytesIO(data)) as img:
            img.seek(0)  # first frame of an animated GIF
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            clean = Image.new(img.mode, img.size)  # fresh image: no metadata carried over
            clean.paste(img)
            out = io.BytesIO()
            clean.save(out, "WEBP", quality=85, method=4)
            return out.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise BadImage("That file isn't a valid image") from e


def store(media_dir: str, data: bytes) -> tuple[uuid.UUID, str]:
    os.makedirs(media_dir, exist_ok=True)
    mid = uuid.uuid4()
    path = os.path.join(media_dir, f"{mid}.webp")
    with open(path, "wb") as f:
        f.write(data)
    return mid, path
