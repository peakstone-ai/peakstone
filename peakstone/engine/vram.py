"""Estimate the largest context window a GGUF model can serve within a VRAM budget — without the
slow "launch llama-server at ever-higher --ctx until it OOMs" loop.

The idea: VRAM use is weights (≈ the GGUF file size, fixed) + the KV cache (grows linearly with the
context length) + a roughly-fixed compute/CUDA overhead (+ a vision projector, if any). The KV cost
per token is computable from the model's geometry (layers, KV-heads, head dim) and the cache dtype
(`--cache-type-k/v`), so the max context is just:

    max_ctx ≈ (usable_vram − weights − overhead − mmproj) / kv_bytes_per_token

That's an instant analytical answer; an optional empirical probe (in the dashboard) can confirm it by
launching once at the estimate. Everything here is pure + dependency-free (stdlib struct only) so it's
unit-testable without a GPU.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

# --- minimal GGUF metadata reader --------------------------------------------------------------
# GGUF is little-endian. We read only the metadata header (never tensor data) and keep the handful of
# keys needed for KV-cache geometry. Layout (v2/v3): magic 'GGUF', u32 version, u64 tensor_count,
# u64 metadata_kv_count, then kv pairs {string key, u32 value-type, typed value}.

_GGUF_MAGIC = 0x46554747  # 'GGUF' as little-endian u32

# value-type enum -> struct format + byte size, for the scalar types
_SCALAR = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("I", 4), 5: ("i", 4),
           6: ("f", 4), 7: ("?", 1), 10: ("Q", 8), 11: ("q", 8), 12: ("d", 8)}
_STRING, _ARRAY = 8, 9


def _skip_array(f, atype: int, alen: int) -> None:
    """Seek past an array value — we never need array contents (e.g. the tokenizer vocab)."""
    if atype in _SCALAR:
        f.seek(_SCALAR[atype][1] * alen, 1)
    elif atype == _STRING:
        for _ in range(alen):
            (n,) = struct.unpack("<Q", f.read(8))
            f.seek(n, 1)
    elif atype == _ARRAY:
        for _ in range(alen):
            at, = struct.unpack("<I", f.read(4))
            al, = struct.unpack("<Q", f.read(8))
            _skip_array(f, at, al)
    else:
        raise ValueError(f"unknown GGUF array element type {atype}")


def _read_value(f, vtype: int):
    """Return a scalar/string value; for arrays, seek past and return None (we keep no array values)."""
    if vtype in _SCALAR:
        fmt, size = _SCALAR[vtype]
        return struct.unpack("<" + fmt, f.read(size))[0]
    if vtype == _STRING:
        (n,) = struct.unpack("<Q", f.read(8))
        return f.read(n).decode("utf-8", "replace")
    if vtype == _ARRAY:
        at, = struct.unpack("<I", f.read(4))
        al, = struct.unpack("<Q", f.read(8))
        _skip_array(f, at, al)
        return None
    raise ValueError(f"unknown GGUF value type {vtype}")


def read_metadata(path: str | Path) -> dict:
    """Parse a GGUF file's metadata into a {key: value} dict (scalars + strings; arrays skipped).
    Raises ValueError if `path` isn't a GGUF file or uses an unsupported (v1) layout."""
    with open(path, "rb") as f:
        magic, version = struct.unpack("<II", f.read(8))
        if magic != _GGUF_MAGIC:
            raise ValueError("not a GGUF file (bad magic)")
        if version < 2:
            raise ValueError(f"unsupported GGUF version {version} (need v2+)")
        _tensor_count, n_kv = struct.unpack("<QQ", f.read(16))
        meta: dict = {}
        for _ in range(n_kv):
            (klen,) = struct.unpack("<Q", f.read(8))
            key = f.read(klen).decode("utf-8", "replace")
            (vtype,) = struct.unpack("<I", f.read(4))
            val = _read_value(f, vtype)
            if val is not None:
                meta[key] = val
    return meta


# --- model geometry ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Geometry:
    """The KV-cache-relevant shape of a model, read from GGUF metadata."""
    arch: str
    n_layer: int
    n_head: int
    n_head_kv: int
    head_dim_k: int
    head_dim_v: int
    n_ctx_train: int | None   # the model's native/trained context window (the hard ceiling)

    def kv_bytes_per_token(self, k_type: str = "f16", v_type: str = "f16") -> float:
        """Bytes of KV cache one token occupies across all layers, for the given cache dtypes."""
        ks = kv_type_size(k_type)
        vs = kv_type_size(v_type)
        return self.n_layer * self.n_head_kv * (self.head_dim_k * ks + self.head_dim_v * vs)


def geometry_from_meta(meta: dict) -> Geometry:
    """Pull KV geometry out of a GGUF metadata dict. Falls back sensibly when optional keys are
    absent (head_count_kv -> head_count for non-GQA; key/value_length -> embedding/head_count)."""
    arch = meta.get("general.architecture", "")

    def g(suffix: str):
        return meta.get(f"{arch}.{suffix}")

    n_layer = g("block_count")
    n_head = g("attention.head_count")
    n_head_kv = g("attention.head_count_kv") or n_head
    n_embd = g("embedding_length")
    if not (n_layer and n_head and n_embd):
        raise ValueError(f"GGUF metadata missing core geometry for arch {arch!r}")
    default_hd = n_embd // n_head
    head_dim_k = g("attention.key_length") or default_hd
    head_dim_v = g("attention.value_length") or default_hd
    return Geometry(arch=arch, n_layer=n_layer, n_head=n_head, n_head_kv=n_head_kv,
                    head_dim_k=head_dim_k, head_dim_v=head_dim_v, n_ctx_train=g("context_length"))


def read_geometry(path: str | Path) -> Geometry:
    return geometry_from_meta(read_metadata(path))


# --- KV cache dtype sizes ----------------------------------------------------------------------
# Effective bytes-per-element for the cache types `--cache-type-k/v` accepts. Quantized types store
# 32-element blocks: q8_0 = 34B/32, q4_0 = 18B/32, etc. (block layout from ggml).
_KV_TYPE_SIZE = {
    "f32": 4.0, "f16": 2.0, "bf16": 2.0,
    "q8_0": 34 / 32, "q8_1": 36 / 32,
    "q5_0": 22 / 32, "q5_1": 24 / 32,
    "q4_0": 18 / 32, "q4_1": 20 / 32,
    "iq4_nl": 18 / 32,
}


def kv_type_size(name: str) -> float:
    """Effective bytes per element for a KV cache dtype (defaults to f16 if unrecognised)."""
    return _KV_TYPE_SIZE.get((name or "f16").lower(), 2.0)


def cache_types_from_flags(flags: str) -> tuple[str, str]:
    """Extract (k_type, v_type) from a serve flags string's --cache-type-k/--cache-type-v; default
    f16. -fa/flash-attention doesn't change KV size, only compute, so it's irrelevant here."""
    k = re.search(r"--cache-type-k\s+(\S+)", flags or "")
    v = re.search(r"--cache-type-v\s+(\S+)", flags or "")
    return (k.group(1) if k else "f16", v.group(1) if v else "f16")


# --- the estimate ------------------------------------------------------------------------------

# Headroom defaults (GiB). The CUDA context + compute graph buffers are roughly fixed for a given
# model; 1.0 GiB is a conservative lump that matches the roster's measured fits. `reserve` keeps the
# card from being driven to 100% (OS/driver/desktop). `safety` shaves the final ctx so the estimate
# errs on the side of "actually fits".
_GIB = 1024 ** 3
DEFAULT_OVERHEAD_GIB = 1.0
DEFAULT_RESERVE_GIB = 0.6
DEFAULT_SAFETY = 0.95


@dataclass(frozen=True)
class CtxEstimate:
    max_ctx: int                 # estimated largest servable context (snapped down, clamped to native)
    kv_bytes_per_token: float
    weights_gib: float
    kv_budget_gib: float         # VRAM left for KV after weights/overhead/reserve/mmproj
    native_ctx: int | None
    capped_by_native: bool       # True if the model's trained window, not VRAM, is the limit


def _snap(ctx: int) -> int:
    """Round a raw token count down to a tidy window (multiple of 1024, and to 'nice' steps when big)
    so we never claim a hair more than fits."""
    if ctx < 1024:
        return max(0, ctx - ctx % 256)
    step = 1024
    for thresh, s in ((131072, 16384), (32768, 8192), (8192, 2048)):
        if ctx >= thresh:
            step = s
            break
    return (ctx // step) * step


def estimate_max_ctx(*, geom: Geometry, weights_bytes: int, vram_gib: float,
                     k_type: str = "f16", v_type: str = "f16", mmproj_bytes: int = 0,
                     overhead_gib: float = DEFAULT_OVERHEAD_GIB,
                     reserve_gib: float = DEFAULT_RESERVE_GIB,
                     safety: float = DEFAULT_SAFETY) -> CtxEstimate:
    """Estimate the max context that fits in `vram_gib` GiB for this model + cache dtypes. Pure math —
    no launches. The result is clamped to the model's native window and snapped down conservatively."""
    kv_per_tok = geom.kv_bytes_per_token(k_type, v_type)
    weights_gib = weights_bytes / _GIB
    kv_budget_gib = vram_gib - weights_gib - overhead_gib - reserve_gib - mmproj_bytes / _GIB
    if kv_budget_gib <= 0 or kv_per_tok <= 0:
        return CtxEstimate(0, kv_per_tok, weights_gib, max(0.0, kv_budget_gib),
                           geom.n_ctx_train, False)
    raw = int(kv_budget_gib * _GIB * safety / kv_per_tok)
    capped = bool(geom.n_ctx_train and raw >= geom.n_ctx_train)
    if capped:
        raw = geom.n_ctx_train
    return CtxEstimate(_snap(raw), kv_per_tok, weights_gib, kv_budget_gib, geom.n_ctx_train, capped)
