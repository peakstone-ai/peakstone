# Peakstone dashboard

A Textual TUI that shows your **local hardware** (live GPU/CPU/RAM meters) next to the public
leaderboard, **auto-filtered to what fits your GPU** — so you can see how the models that actually
run on your hardware compare, and at what tok/s.

```bash
pip install -e ".[dashboard]"      # or:  pip install peakstone[dashboard]
peakstone                          # or:  python -m peakstone.dashboard  [--api URL]
```

By default it talks to the public instance at `https://peakstone.ai/api` (override with
`$PEAKSTONE_API_URL`). Pass `--api http://localhost:8000` to point at a local/self-hosted server.

## Keys
| key | action |
|---|---|
| `f` | toggle the "fits my hardware" VRAM filter |
| `s` | cycle the sort axis (code / agentic / planner / tok-s) |
| `⏎` | **reproduce** the selected model on your hardware (serve → bench → your tok/s vs published) |
| `s` | (in the reproduce view) **submit** the reproduced run to the leaderboard |
| `m` | **models** — list local models; `r` run (bench it locally → real, submittable data), `a` add (HF repo + file), `d` download (live progress bar) |
| `h` | **history** — past reproduce runs (your tok/s vs published, code score) |
| `r` | refresh the leaderboard |
| `q` | quit |

## Layout
- **Hardware panel** — per-GPU VRAM used/total + utilization, CPU %, RAM used/total, refreshed every
  second (`hardware.py`: `nvidia-smi` + `/proc`, no heavy deps).
- **Leaderboard** — the best run per family from the API, scoped to your max single-GPU VRAM, with
  the published tok/s, VRAM, and trust tier.

## Reproduce a run
Select a row and press `⏎`. The dashboard ensures the model is present (downloading it via `hf` if
not), serves it (`serve/serve.sh` → llama-server), benches a short challenge set with the engine,
then shows **your tok/s vs the published number** (and the ratio) plus the code score it got. Needs
`llama-server` (set `LLAMA_SERVER`, default `~/llama.cpp/build/bin/llama-server`) and a GPU.

`reproduce.py` keeps the serve / health / bench / stop steps as injectable seams, so the
orchestration is unit-tested without a GPU; `models.py` manages the `serve/models.toml` registry +
`hf` downloads. After a successful reproduce, press `s` to **submit** the (already-signed) bundle to
the leaderboard. Every run is logged to `~/.peakstone/repro-history.json` and shown under `h`.
Downloads show a live progress bar (size polled against the HF file size).

## Roadmap (next slices)
- Speculative/draft-model and quant comparison side-by-side.
- Background queue: reproduce several models in sequence.
