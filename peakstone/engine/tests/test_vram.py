"""Analytical ctx estimate (engine/vram.py) + the serve-time ctx resolver (engine/serving.py).

Both are pure given injected GGUF-geometry / VRAM readers, so this runs without a GPU or a real GGUF.
"""
from peakstone.engine import serving, vram
from peakstone.engine.vram import Geometry


def _geom(*, n_layer=80, n_head_kv=8, head_dim=128, native=32768):
    return Geometry(arch="llama", n_layer=n_layer, n_head=n_layer and 64, n_head_kv=n_head_kv,
                    head_dim_k=head_dim, head_dim_v=head_dim, n_ctx_train=native)


def test_kv_bytes_and_cache_types():
    g = _geom(n_layer=2, n_head_kv=4, head_dim=128)
    assert g.kv_bytes_per_token("f16", "f16") == 2 * 4 * (128 * 2 + 128 * 2)
    # q8_0 KV is smaller than f16 -> fewer bytes/token
    assert g.kv_bytes_per_token("q8_0", "q8_0") < g.kv_bytes_per_token("f16", "f16")
    assert vram.cache_types_from_flags("-fa --cache-type-k q8_0 --cache-type-v q5_1") == ("q8_0", "q5_1")
    assert vram.cache_types_from_flags("-ngl 99") == ("f16", "f16")


def test_estimate_caps_at_native_window():
    # tiny weights + huge VRAM -> the trained window, not VRAM, is the limit
    est = vram.estimate_max_ctx(geom=_geom(native=8192), weights_bytes=1_000, vram_gib=80)
    assert est.capped_by_native and est.max_ctx == 8192


def test_estimate_shrinks_with_vram():
    geom = _geom(n_layer=80, n_head_kv=8, head_dim=128, native=131072)
    big = vram.estimate_max_ctx(geom=geom, weights_bytes=1_000, vram_gib=24)
    small = vram.estimate_max_ctx(geom=geom, weights_bytes=1_000, vram_gib=8)
    assert 0 < small.max_ctx < big.max_ctx < 131072        # VRAM-bound, snapped, below native
    assert small.max_ctx % 1024 == 0                       # snapped to a tidy window


def test_estimate_zero_when_weights_exceed_vram():
    est = vram.estimate_max_ctx(geom=_geom(), weights_bytes=30 * 1024**3, vram_gib=24)
    assert est.max_ctx == 0                                 # doesn't fit at all


def _model(tmp_path, *, ctx=None, flags="", make_file=True):
    f = tmp_path / "m.gguf"
    if make_file:
        f.write_bytes(b"\0" * 4096)                         # tiny stand-in (weights ~ 0 GiB)
    return serving.ServeModel("m", 8081, ctx, str(f) if make_file else None, flags, None)


def test_resolve_ctx_estimates_when_unconfigured(tmp_path):
    choice = serving.resolve_ctx(_model(tmp_path), vram_gib=8, _read_geometry=lambda p: _geom())
    assert choice.source == "estimated" and choice.ctx and choice.ctx % 1024 == 0


def test_resolve_ctx_configured_wins_and_warns_if_too_big(tmp_path):
    choice = serving.resolve_ctx(_model(tmp_path, ctx=131072), vram_gib=8,
                                 _read_geometry=lambda p: _geom())
    assert choice.source == "configured" and choice.ctx == 131072
    assert choice.warning and "may OOM" in choice.warning   # configured exceeds the rough fit
    # a configured ctx that fits draws no warning
    ok = serving.resolve_ctx(_model(tmp_path, ctx=4096), vram_gib=8, _read_geometry=lambda p: _geom())
    assert ok.source == "configured" and ok.warning is None


def test_resolve_ctx_skips_offloaded_models(tmp_path):
    # --n-cpu-moe puts weights on the host CPU, which the analytical math can't model -> no estimate
    choice = serving.resolve_ctx(_model(tmp_path, flags="--n-cpu-moe 1"), vram_gib=8,
                                 _read_geometry=lambda p: _geom())
    assert choice.source == "fallback" and choice.ctx is None and "n-cpu-moe" in choice.warning


def test_resolve_ctx_falls_back_without_weights(tmp_path):
    choice = serving.resolve_ctx(_model(tmp_path, make_file=False), vram_gib=8)
    assert choice.source == "fallback" and choice.ctx is None


def test_detect_vram_gib_parses_nvidia_smi():
    class _Out:
        stdout = "24564\n"
    assert round(serving.detect_vram_gib(run=lambda *a, **k: _Out())) == 24
