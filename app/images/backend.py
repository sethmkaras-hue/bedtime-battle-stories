"""Lazy CPU-only diffusion. Never imported by FastAPI startup."""

from .hardware import check


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
            torch_dtype=torch.float32,
            use_safetensors=True,
        )
        self.info["scheduler"] = self.pipeline.scheduler.__class__.__name__
        self.pipeline.to("cpu")
        self.pipeline.enable_attention_slicing("max")
        self.pipeline.enable_vae_slicing()
        self.pipeline.set_progress_bar_config(disable=True)

    def _embeddings(self, positive, negative):
        # CLIP has 77-token windows. Encode bounded chunks instead of silently
        # losing scientific details or the shared art direction to truncation.
        tokenizer = self.pipeline.tokenizer
        rows = [
            tokenizer.encode(text, add_special_tokens=False)
            for text in (positive, negative)
        ]
        chunks = max((len(row) + 74) // 75 for row in rows)
        self.info["prompt_windows"] = chunks
        if chunks > 4:
            raise ValueError("Prompt exceeds the supported four CLIP windows")
        result = []
        for tokens in rows:
            pieces = []
            for n in range(chunks):
                values = (
                    [tokenizer.bos_token_id]
                    + tokens[n * 75 : (n + 1) * 75]
                    + [tokenizer.eos_token_id]
                )
                values += [tokenizer.pad_token_id] * (77 - len(values))
                pieces.append(
                    self.pipeline.text_encoder(
                        self.torch.tensor([values], device="cpu")
                    )[0]
                )
            result.append(self.torch.cat(pieces, dim=1))
        return result

    def generate(
        self, settings, destination, stop=lambda: False, progress=lambda step: None
    ):
        with self.torch.inference_mode():
            positive, negative = self._embeddings(
                settings["prompt"], settings["negative_prompt"]
            )

            def step(pipe, index, timestep, kwargs):
                if stop():
                    raise Interrupted(
                        "Generation interrupted; resume will retry this image"
                    )
                progress(index + 1)
                return kwargs

            result = self.pipeline(
                prompt_embeds=positive,
                negative_prompt_embeds=negative,
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
