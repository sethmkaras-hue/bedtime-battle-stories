"""Lazy CPU-only diffusion. Never imported by FastAPI startup."""

import logging

from .hardware import check
from .prompts import fit_prompts


class Interrupted(RuntimeError):
    pass


class DiffusionBackend:
    def __init__(self, settings):
        check(settings)
        import os

        os.environ["OMP_NUM_THREADS"] = str(settings["threads"])
        os.environ["MKL_NUM_THREADS"] = str(settings["threads"])
        os.environ["OPENBLAS_NUM_THREADS"] = "1"
        import torch
        from diffusers import StableDiffusionPipeline

        torch.set_num_threads(settings["threads"])
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        import diffusers, transformers, platform

        self.info = {
            "torch": torch.__version__,
            "diffusers": diffusers.__version__,
            "transformers": transformers.__version__,
            "python": platform.python_version(),
        }
        self.torch = torch
        self.pipeline = StableDiffusionPipeline.from_pretrained(
            settings["model_path"],
            local_files_only=True,
            use_safetensors=True,
        )
        self.info["scheduler"] = self.pipeline.scheduler.__class__.__name__
        self.pipeline.to(device="cpu", dtype=torch.float32)
        self.pipeline.enable_attention_slicing("max")
        self.pipeline.enable_vae_slicing()
        self.pipeline.set_progress_bar_config(disable=True)

    def generate(
        self, settings, destination, stop=lambda: False, progress=lambda step: None
    ):
        with self.torch.inference_mode():
            final = fit_prompts(
                settings,
                self.pipeline.tokenizer,
                self.pipeline.text_encoder.config.max_position_embeddings,
            )
            # Persist the exact prompts used, not just their unbudgeted recipe.
            settings.update(final)
            logger = logging.getLogger("creature_images")
            for field, count in (
                ("prompt", final["prompt_token_count"]),
                ("negative_prompt", final["negative_prompt_token_count"]),
            ):
                message = (
                    f"creature={settings.get('scientific_name', 'unknown')} "
                    f"{field} tokens={count}/{final['prompt_token_limit']} "
                    f"(including special tokens): {final[field]}"
                )
                logger.info(message)
                print(message, flush=True)

            def step(pipe, index, timestep, kwargs):
                if stop():
                    raise Interrupted(
                        "Generation interrupted; resume will retry this image"
                    )
                progress(index + 1)
                return kwargs

            result = self.pipeline(
                prompt=final["prompt"],
                negative_prompt=final["negative_prompt"],
                width=settings["resolution"],
                height=settings["resolution"],
                num_inference_steps=settings["steps"],
                guidance_scale=settings["guidance"],
                generator=self.torch.Generator(device="cpu").manual_seed(
                    settings["seed"]
                ),
                num_images_per_prompt=1,
                callback_on_step_end=step,
            )
            if result.nsfw_content_detected and any(result.nsfw_content_detected):
                raise ValueError(
                    "Model safety checker rejected the image; previous artwork preserved"
                )
            result.images[0].save(destination, format="PNG")

    def close(self):
        self.pipeline = None
        import gc

        gc.collect()
