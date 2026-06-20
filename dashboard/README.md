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
| `r` | refresh the leaderboard |
| `q` | quit |

## Layout
- **Hardware panel** — per-GPU VRAM used/total + utilization, CPU %, RAM used/total, refreshed every
  second (`hardware.py`: `nvidia-smi` + `/proc`, no heavy deps).
- **Leaderboard** — the best run per family from the API, scoped to your max single-GPU VRAM, with
  the published tok/s, VRAM, and trust tier.

## Roadmap (next slices)
- **Reproduce a run** — pick a fitting row; the dashboard serves the model + runs the bench locally
  and shows *your* live tok/s vs the published number.
- **Submit** signed runs from the TUI, and **add/manage local models** (edit the serve config).
