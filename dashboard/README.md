# Peakstone dashboard

A Textual TUI that shows your **local hardware** (live GPU/CPU/RAM meters) next to the public
leaderboard, **auto-filtered to what fits your GPU** — so you can see how the models that actually
run on your hardware compare, and at what tok/s.

```bash
pip install -e ".[dashboard]"      # or:  pip install peakstone[dashboard]
peakstone                          # or:  python -m dashboard  [--api URL]
```

By default it talks to `$PEAKSTONE_API_URL` (or `http://localhost:8000`). Pass `--api https://peakstone.ai`
for the public instance.

## Keys
| key | action |
|---|---|
| `f` | toggle the "fits my hardware" VRAM filter |
| `s` | cycle the sort axis (code / agentic / planner / tok-s) |
| `⏎` | **reproduce** the selected model on your hardware (serve → bench → your tok/s vs published) |
| `m` | **models** — list local models, `a` add (HF repo + file), `d` download |
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
`hf` downloads.

## Roadmap (next slices)
- **Submit** signed runs from the TUI (POST a bundle after a reproduce).
- Live download progress bars; per-run history.
