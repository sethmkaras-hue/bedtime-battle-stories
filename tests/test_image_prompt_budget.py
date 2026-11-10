"""Offline token-budget regression tests; no model weights or network calls."""
import contextlib
import json
from types import SimpleNamespace

import pytest

from app.images.prompts import fit_prompts, prompt, token_ids
from app.images.backend import DiffusionBackend


class SubwordTokenizer:
    """Deterministic split-heavy tokenizer to catch word-count assumptions."""
    model_max_length = 77

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def encode(self, text, add_special_tokens=True, **kwargs):
        assert kwargs == {"truncation": False, "verbose": False}
        pieces = [ord(c) for c in text if not c.isspace()]
        return [1, *pieces, 2] if add_special_tokens else pieces


@pytest.fixture
def creature():
    return {
        "scientific_name": "Tyrannosaurus rex",
        "category": "dinosaur",
        "verification_status": "verified",
        "physical_characteristics": ["Large skull, short forelimbs. " * 100],
        "description": "Long inspected description. " * 200,
    }


def test_long_tyrannosaurus_preserves_name_and_prioritizes_anatomy(creature):
    tokenizer = SubwordTokenizer()
    result = fit_prompts({**prompt(creature), **creature}, tokenizer, 77)
    assert result["prompt"].startswith("Tyrannosaurus rex. Large skull")
    assert "natural lighting" not in result["prompt"]
    assert result["prompt_token_count"] <= 77
    assert result["negative_prompt_token_count"] <= 77
    assert result["prompt_special_tokens"] == 2
    assert result["prompt_token_count"] == len(token_ids(tokenizer, result["prompt"]))


def test_actual_encoder_limit_wins_and_reserves_specials(creature):
    result = fit_prompts({**prompt(creature), **creature}, SubwordTokenizer(), 32)
    assert result["prompt_token_limit"] == 32
    assert len(token_ids(SubwordTokenizer(), result["prompt"])) <= 32
    assert result["prompt"].startswith("Tyrannosaurus rex")


def test_unfit_name_fails_instead_of_changing_species(creature):
    with pytest.raises(ValueError, match="Scientific creature name"):
        fit_prompts({**prompt(creature), **creature}, SubwordTokenizer(), 10)


def test_special_token_only_budget_fails(creature):
    with pytest.raises(ValueError, match="special tokens"):
        fit_prompts({**prompt(creature), **creature}, SubwordTokenizer(), 2)


def test_short_prompts_unchanged_and_negative_prompt_equally_bounded():
    settings = {"prompt_components": ["rex", "body", "style", "habitat", "light"],
                "negative_prompt": "gore, text"}
    result = fit_prompts(settings, SubwordTokenizer(), 77)
    assert result["prompt"] == "rex. body. style. habitat. light"
    assert result["negative_prompt"] == "gore. text"
    settings["negative_prompt"] = ", ".join(["watermark"] * 100)
    result = fit_prompts(settings, SubwordTokenizer(), 77)
    assert result["negative_prompt_token_count"] <= 77


def test_legacy_queued_job_rebuilds_priority_order(creature):
    settings = {"scientific_name": creature["scientific_name"],
                "scientific_details": ["Large skull"],
                "prompt": "Old overly long prompt " * 200,
                "negative_prompt": "gore, text"}
    result = fit_prompts(settings, SubwordTokenizer(), 77)
    assert result["prompt"].startswith("Tyrannosaurus rex. Large skull")
    assert result["prompt_token_count"] <= 77
    # Caller retains original queue data; budgeting is explicit, not destructive.
    assert settings["prompt"].startswith("Old")


def test_component_priority_order(creature):
    creature["physical_characteristics"] = ["large skull"]
    creature["description"] = "two short forelimbs"
    parts = prompt(creature)["prompt_components"]
    assert parts[0] == "Tyrannosaurus rex"
    assert parts.index("large skull") < next(i for i, s in enumerate(parts) if "full-body" in s)
    assert next(i for i, s in enumerate(parts) if "full-body" in s) < next(i for i, s in enumerate(parts) if "encyclopedia" in s)
    assert next(i for i, s in enumerate(parts) if "encyclopedia" in s) < next(i for i, s in enumerate(parts) if "terrestrial" in s)
    assert parts[-1] == "natural lighting, sharp focus"


def test_tyrannosaurus_generation_adapter_logs_and_passes_only_bounded_text(creature, tmp_path, caplog):
    """Exercise generate(), logging and recorded settings with a fake renderer."""
    backend = DiffusionBackend.__new__(DiffusionBackend)
    backend.torch = SimpleNamespace(
        inference_mode=contextlib.nullcontext,
        Generator=lambda device: SimpleNamespace(manual_seed=lambda seed: seed),
    )
    calls = []

    class Image:
        def save(self, destination, format):
            destination.write_bytes(b"mock renderer, not a real image")

    class Pipeline:
        tokenizer = SubwordTokenizer()
        text_encoder = SimpleNamespace(config=SimpleNamespace(max_position_embeddings=77))

        def __call__(self, **kwargs):
            calls.append(kwargs)
            assert "prompt_embeds" not in kwargs
            for field in ("prompt", "negative_prompt"):
                assert len(token_ids(self.tokenizer, kwargs[field])) <= 77
            return SimpleNamespace(nsfw_content_detected=[False], images=[Image()])

    backend.pipeline = Pipeline()
    settings = {**prompt(creature), **creature, "resolution": 512, "steps": 20,
                "guidance": 7.5, "seed": 42}
    caplog.set_level("INFO", logger="creature_images")
    backend.generate(settings, tmp_path / "tyrannosaurus.png")
    assert calls[0]["num_inference_steps"] == 20
    assert calls[0]["width"] == 512 and calls[0]["guidance_scale"] == 7.5
    assert settings["prompt"] == calls[0]["prompt"]
    assert settings["prompt_token_count"] <= 77
    assert "Tyrannosaurus rex" in caplog.text and "tokens=" in caplog.text
    assert "negative_prompt tokens=" in caplog.text


def test_real_clip_tokenizer_counts_subwords_and_specials(creature, tmp_path):
    """Real tokenizer algorithm with a tiny offline vocabulary, no weights."""
    transformers = pytest.importorskip("transformers")
    from transformers.models.clip.tokenization_clip import bytes_to_unicode

    symbols = list(bytes_to_unicode().values())
    vocab = symbols + [s + "</w>" for s in symbols]
    vocab += ["<|startoftext|>", "<|endoftext|>"]
    (tmp_path / "vocab.json").write_text(json.dumps(dict(zip(vocab, range(len(vocab))))))
    (tmp_path / "merges.txt").write_text("#version: 0.2\n")
    tokenizer = transformers.CLIPTokenizer(
        vocab_file=str(tmp_path / "vocab.json"),
        merges_file=str(tmp_path / "merges.txt"), model_max_length=77,
    )
    result = fit_prompts({**prompt(creature), **creature}, tokenizer, 77)
    for field, count in (("prompt", "prompt_token_count"),
                         ("negative_prompt", "negative_prompt_token_count")):
        encoded = tokenizer(result[field], truncation=False)["input_ids"]
        assert len(encoded) == result[count] <= 77
        assert encoded[0] == tokenizer.bos_token_id
        assert encoded[-1] == tokenizer.eos_token_id
    assert result["prompt"].startswith("Tyrannosaurus rex")


def test_tyrannosaurus_tiny_cpu_diffusion(tmp_path, creature):
    """Real CPU inference with tiny RANDOM weights; no pretrained-art claim."""
    torch = pytest.importorskip("torch")
    diffusers = pytest.importorskip("diffusers")
    transformers = pytest.importorskip("transformers")
    from transformers.models.clip.tokenization_clip import bytes_to_unicode

    symbols = list(bytes_to_unicode().values())
    vocab = symbols + [s + "</w>" for s in symbols]
    vocab += ["<|startoftext|>", "<|endoftext|>"]
    (tmp_path / "vocab.json").write_text(json.dumps(dict(zip(vocab, range(len(vocab))))))
    (tmp_path / "merges.txt").write_text("#version: 0.2\n")
    tokenizer = transformers.CLIPTokenizer(
        vocab_file=str(tmp_path / "vocab.json"),
        merges_file=str(tmp_path / "merges.txt"), model_max_length=77,
    )
    text_encoder = transformers.CLIPTextModel(transformers.CLIPTextConfig(
        vocab_size=len(vocab), hidden_size=32, intermediate_size=64,
        num_hidden_layers=1, num_attention_heads=4, max_position_embeddings=77,
        bos_token_id=tokenizer.bos_token_id, eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id,
    ))
    unet = diffusers.UNet2DConditionModel(
        sample_size=32, in_channels=4, out_channels=4, layers_per_block=1,
        block_out_channels=(32,), down_block_types=("CrossAttnDownBlock2D",),
        up_block_types=("CrossAttnUpBlock2D",), cross_attention_dim=32,
        attention_head_dim=4,
    )
    vae = diffusers.AutoencoderKL(
        in_channels=3, out_channels=3, latent_channels=4,
        down_block_types=("DownEncoderBlock2D", "DownEncoderBlock2D"),
        up_block_types=("UpDecoderBlock2D", "UpDecoderBlock2D"),
        block_out_channels=(32, 32), layers_per_block=1,
        norm_num_groups=8, sample_size=64,
    )
    pipeline = diffusers.StableDiffusionPipeline(
        vae=vae, text_encoder=text_encoder, tokenizer=tokenizer, unet=unet,
        scheduler=diffusers.DDIMScheduler(steps_offset=1, clip_sample=False), safety_checker=None,
        feature_extractor=None, requires_safety_checker=False,
    )
    model = tmp_path / "tiny-random-model"
    pipeline.save_pretrained(model, safe_serialization=True)
    settings = {**prompt(creature), **creature, "resolution": 64,
                "steps": 2, "guidance": 7.5, "seed": 42,
                "threads": 1, "model_path": str(model)}
    backend = DiffusionBackend(settings)
    try:
        destination = tmp_path / "tyrannosaurus-random-weights.png"
        backend.generate(settings, destination)
        from PIL import Image
        with Image.open(destination) as image:
            assert image.size == (64, 64)
        assert next(backend.pipeline.unet.parameters()).device.type == "cpu"
        assert next(backend.pipeline.unet.parameters()).dtype == torch.float32
        assert settings["prompt_token_count"] <= 77
        assert settings["negative_prompt_token_count"] <= 77
    finally:
        backend.close()


def test_exact_special_token_boundary():
    settings = {"prompt_components": ["x" * 75], "negative_prompt": "y" * 75}
    result = fit_prompts(settings, SubwordTokenizer(), 77)
    assert result["prompt_token_count"] == 77
    assert result["negative_prompt_token_count"] == 77
    settings["prompt_components"] = ["x" * 76]
    with pytest.raises(ValueError, match="Scientific creature name"):
        fit_prompts(settings, SubwordTokenizer(), 77)


def test_tokenizer_limit_also_enforced(creature):
    tokenizer = SubwordTokenizer()
    tokenizer.model_max_length = 50
    result = fit_prompts({**prompt(creature), **creature}, tokenizer, 77)
    assert result["prompt_token_limit"] == 50
    assert result["prompt_token_count"] <= 50
    assert result["negative_prompt_token_count"] <= 50
