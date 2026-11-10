#!/usr/bin/env python3
"""Explicit model download in the isolated Python 3.12 runtime."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.images.core import MODEL_ID, MODEL_LICENSE, model_root
from app.images.hardware import hardware


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--model-license")
    args = parser.parse_args()
    if args.model != MODEL_ID and not args.model_license:
        parser.error(
            "Custom models require --model-license after reviewing their license"
        )
    print(json.dumps(hardware(), indent=2))
    if not args.download:
        return 0
    from huggingface_hub import snapshot_download

    folder = model_root()
    folder.mkdir(parents=True, exist_ok=True)
    # Only safetensors inference components; omit unsafe pickle/checkpoint and GPU variants.
    snapshot = Path(
        snapshot_download(
            args.model,
            revision=args.revision,
            cache_dir=str(folder / "hub"),
            max_workers=2,
            allow_patterns=[
                "model_index.json",
                "scheduler/*",
                "tokenizer/*",
                "feature_extractor/*",
                "text_encoder/config.json",
                "text_encoder/model.safetensors",
                "unet/config.json",
                "unet/diffusion_pytorch_model.safetensors",
                "vae/config.json",
                "vae/diffusion_pytorch_model.safetensors",
                "safety_checker/config.json",
                "safety_checker/model.safetensors",
                "README.md",
                "LICENSE*",
            ],
        )
    )
    required = [
        "model_index.json",
        "unet/diffusion_pytorch_model.safetensors",
        "vae/diffusion_pytorch_model.safetensors",
        "text_encoder/model.safetensors",
        "tokenizer/vocab.json",
        "tokenizer/merges.txt",
        "scheduler/scheduler_config.json",
    ]
    index = json.loads((snapshot / "model_index.json").read_text())
    if index.get("_class_name") != "StableDiffusionPipeline":
        raise ValueError(
            "Choose a Stable Diffusion 1.x/2.x pipeline; SDXL/FLUX are not supported by this CPU preset"
        )
    if index.get("safety_checker") and index["safety_checker"][0]:
        required += [
            "safety_checker/model.safetensors",
            "feature_extractor/preprocessor_config.json",
        ]
    missing = [name for name in required if not (snapshot / name).is_file()]
    if missing:
        raise ValueError("Model snapshot is incomplete: " + ", ".join(missing))
    revision = snapshot.name
    manifest = {
        "model": args.model,
        "revision": revision,
        "model_path": str(snapshot.resolve()),
        "license": args.model_license or MODEL_LICENSE,
        "required_files": required,
    }
    target = folder / "image-model.json"
    temporary = target.with_suffix(".part")
    temporary.write_text(json.dumps(manifest, indent=2))
    temporary.replace(target)
    print("Cached model:", snapshot, "revision:", revision)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Model setup failed: " + str(error), file=sys.stderr)
        raise SystemExit(2)
