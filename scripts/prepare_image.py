#!/usr/bin/env python3
"""Optimize an already licensed, identified source image without network access."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.library import Image, local_asset


def prepare(source, metadata, key):
    from PIL import Image as PILImage, ImageOps

    record = Image.model_validate(metadata)
    if record.placeholder:
        raise ValueError(
            "Supply reviewed real-image attribution, not placeholder metadata"
        )
    if not key.replace("-", "").isalnum():
        raise ValueError("Use an alphanumeric media key")
    digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()[:16]
    folder = local_asset("/static/creatures/" + key + "-" + digest)
    folder.mkdir(parents=True, exist_ok=True)
    variants = {}
    with PILImage.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        for width in [320, 640, 960]:
            variant = image.copy()
            variant.thumbnail((width, width))
            actual_width = variant.width
            if str(actual_width) in variants:
                continue
            path = folder / f"{actual_width}.webp"
            temporary = path.with_suffix(".part")
            try:
                variant.save(temporary, format="WEBP", quality=85, method=6)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            variants[str(actual_width)] = "/" + str(
                path.relative_to(local_asset("/static/").parent)
            )
    record.path = (
        variants[str(min(max(map(int, variants)), 640))]
        if "640" in variants
        else variants[max(variants, key=int)]
    )
    record.variants = variants
    record.modifications = (
        (record.modifications or "")
        + "; EXIF orientation normalized, metadata removed, resized and converted to WebP."
    )
    return record.model_dump(mode="json")


def cli():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("metadata", type=Path)
    p.add_argument("--key", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = prepare(a.source, json.loads(a.metadata.read_text()), a.key)
    a.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    cli()
