"""Eval harness entrypoint.

Examples:
  # sanity-check the suite itself against reference solutions (no model needed)
  python -m engine.runner --reference --models reference

  # run two models over the whole suite
  python -m engine.runner --models glm-4.7-flash,qwen3-coder

  # one language, easy challenges only, no judge
  python -m engine.runner --models devstral --lang python --difficulty 1,2 --no-judge
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tomllib
from pathlib import Path

from . import capabilities, global_rules, paths
from .levels import (GATED_CAP, load_levels, model_capabilities, relevant, resolve as resolve_level,
                     resolve_env)
from .challenges import filter_challenges, load_challenges
from .extract import extract_files
from .judge import judge_solution
from .provider import LLMClient
from .report import write_report
from .sandbox import effective_sandbox, run_tests
from .scoring import compute_score

ROOT = paths.repo_root()   # results land here; data files resolve via engine.paths

# --stream-output protocol constants live in streamproto.py (ONE declaration shared with the
# dashboard — review R21); re-exported here so existing imports keep working.
from .streamproto import GEN_ATTEMPT, GEN_MARK, GEN_NL, GEN_PHASE  # noqa: F401

# Per-scoring-mode handlers live in handlers.py (review C10): one handler per scoring mode, each
# returning a typed RowResult; main() below is the thin loop that owns streak/skip bookkeeping.
# The helpers that moved with them are re-exported so existing imports (tests, env.planner) keep
# working — same convention as the streamproto re-export above.
from .handlers import (DEFAULT_MAX_TOKENS, REASONING_MAX_TOKENS, SYSTEM_PROMPT,  # noqa: F401
                       HandlerContext, RowResult, _budget, _cap, _emit_gen, _emit_phase,
                       _metacog, _row, _select_env_provider, handler_for, run_env_axis,
                       run_tool_conversation)


def _judge_client(args, jcfg, host, ports, judge_model):
    """The judge's endpoint: explicit [judge].base_url > the swapping gateway (when --gateway —
    the per-port client would point at a llama-server that doesn't exist in gateway mode, so every
    judge call errored and both/judge challenges silently degraded to tests-only) > per-model port."""
    if jcfg.get("base_url"):
        return LLMClient(jcfg["base_url"], jcfg.get("api_key", ""))
    if args.gateway:
        return LLMClient(args.gateway, api_key=args.gateway_key or "")
    if judge_model not in ports:
        print(f"!! judge model '{judge_model}' not in config [models]", file=sys.stderr)
        return None
    return LLMClient(f"http://{host}:{ports[judge_model]}")


def _freeze_budget(args, run_cfg) -> None:
    """Resolve the token budget ONCE and pin it in run_cfg — every later consumer (per-challenge
    requests, meta, the signed bundle's sampling block) reads the same numbers. Without this, a CLI
    --max-tokens, the config value, and the meta default could describe one run three ways."""
    run_cfg["max_tokens"], run_cfg["max_tokens_reasoning"] = (
        _budget(args, run_cfg), _budget(args, run_cfg, reasoning_heavy=True))


def update_loop_streak(family, *, won, looped, streaks, passed, abandoned, threshold):
    """Update per-category repetition-loop tracking after one challenge result; return True if the
    category should now be abandoned (it just hit `threshold` CONSECUTIVE repetition-loop failures with
    no pass). A pass resets the streak and immunizes the category. Mutates streaks/passed/abandoned.

    Pure (no I/O) so the non-viability policy is unit-testable apart from the big run loop."""
    if won:
        passed.add(family)
        streaks[family] = 0
    elif looped:
        streaks[family] = streaks.get(family, 0) + 1
    else:
        streaks[family] = 0          # a non-loop failure breaks the consecutive streak
    if family not in passed and streaks.get(family, 0) >= threshold and family not in abandoned:
        abandoned.add(family)
        return True
    return False


class _PipeSafe:
    """Wrap a stream so a dead reader can't kill the run: if the consumer of our stdout (e.g. the TUI
    run viewer) crashes or is killed, the next write would raise BrokenPipeError and take the whole
    run down with it. Here, once the pipe breaks, writes become no-ops and the run continues to
    completion (results.json still gets written). Applied only at the CLI entry point."""

    def __init__(self, wrapped):
        self._w = wrapped
        self._broken = False

    def write(self, s):
        if self._broken:
            return len(s)
        try:
            return self._w.write(s)
        except (BrokenPipeError, OSError):
            self._broken = True
            return len(s)

    def flush(self):
        if not self._broken:
            try:
                self._w.flush()
            except (BrokenPipeError, OSError):
                self._broken = True

    def __getattr__(self, name):
        return getattr(self._w, name)


# System prompt for the planner phase of the planner eval (--gen-plans). The planner writes a
# spec/plan a coder will execute; it must NOT write the solution itself.
PLAN_SYSTEM = (
    "You are a senior software architect. Given a programming task, write a concise but COMPLETE "
    "implementation plan that a developer can follow to a fully correct solution. Cover: the file "
    "and function/type signatures to define, the core data structures, the algorithm step by step, "
    "and the tricky edge cases and error conditions to handle. Do NOT write the final solution "
    "code — output the plan only, as prose and bullet points."
)


def _csv(s):
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _gpu_mem_used():
    """Total GPU memory currently in use (MiB), or None if nvidia-smi is unavailable.

    Sampled while a single model server is loaded, so it reflects that model's footprint
    (weights + KV cache + compute buffers) at the configured context length.
    """
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:  # noqa: BLE001
        return None


def _server_ram_used():
    """Resident host memory (MiB) of the running llama-server(s) — the model's RAM footprint, which is
    large when layers are CPU-offloaded (a model too big for VRAM still runs, spilling here). None if
    it can't be determined. Sampled while the one model is loaded."""
    import subprocess
    try:
        pids = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True,
                              timeout=5).stdout.split()
    except Exception:  # noqa: BLE001
        return None
    total = 0
    for pid in pids:
        try:
            if sys.platform == "darwin":
                r = subprocess.run(["ps", "-o", "rss=", "-p", pid], capture_output=True, text=True, timeout=5)
                total += int(r.stdout.strip() or 0)          # KiB
            else:
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])        # KiB
                        break
        except Exception:  # noqa: BLE001
            continue
    return round(total / 1024) if total else None            # KiB -> MiB


def _gpu_info():
    """GPU name + NVIDIA driver version for the run (or None if nvidia-smi is unavailable).

    Recorded once per run (a host constant, unlike per-model VRAM) so the report can attribute
    a tok/s shift to a driver change — e.g. after an apt upgrade swaps the driver branch.
    """
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()
        if not out:
            return None
        name, _, driver = out[0].partition(",")
        return {"name": name.strip(), "driver_version": driver.strip()}
    except Exception:  # noqa: BLE001
        return None


def _host_load():
    """Coarse contention snapshot taken once at run start — load average + GPU utilization + how many
    compute processes are sharing the GPU. Recorded so a slow tok/s can be ATTRIBUTED to a busy box;
    correctness scores are deterministic and load-independent, so they're never adjusted for it."""
    import shutil
    import subprocess
    snap: dict = {}
    try:
        snap["load_avg_1m"] = round(os.getloadavg()[0], 2)
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("nvidia-smi"):
        try:
            u = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
            snap["gpu_util_pct"] = int(u.stdout.split("\n")[0])
        except Exception:  # noqa: BLE001
            pass
        try:
            p = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=10)
            snap["gpu_procs"] = len([x for x in p.stdout.splitlines() if x.strip()])
        except Exception:  # noqa: BLE001
            pass
    return snap or None


def main(argv=None):
    from . import versions
    _install_pipe_safety()   # every entry point (module, console script, daemon subprocess)
    ap = argparse.ArgumentParser(description="Local coding-LLM eval harness")
    ap.add_argument("--version", action="version", version=f"peakstone {versions.pkg_version()}")
    ap.add_argument("--update", action="store_true",
                    help="upgrade the installed peakstone client (same as `peakstone update`), then exit")
    ap.add_argument("--models",
                    help="comma list of model names (must be in config [models]); "
                         "use 'reference' with --reference. Not needed with --judge-only.")
    ap.add_argument("--lang", help="comma list: python,javascript,typescript,go,rust")
    ap.add_argument("--difficulty", help="comma list of 1..5")
    ap.add_argument("--ids", help="comma list of specific challenge ids")
    ap.add_argument("--ids-file", help="path to a file of challenge ids (newline/comma separated); "
                    "unioned with --ids. Lets the TUI pass a large selection without argv limits.")
    ap.add_argument("--type", help="comma list of types: basic,algorithms,data,math,"
                    "lib-knowledge,concurrency,data-structures,typing,tool-calling")
    ap.add_argument("--family", help="comma list of corpus families (challenges/<dir>): "
                    "humaneval,bigcodebench,livecodebench,python,go,...")
    ap.add_argument("--published-after", help="keep challenges with published_at on/after YYYY-MM-DD")
    ap.add_argument("--published-before", help="keep challenges with published_at on/before YYYY-MM-DD")
    ap.add_argument("--agent", action="store_true",
                    help="for repo-patch (SWE-bench) challenges, drive a multi-turn agent that edits "
                         "the live repo via tools instead of one-shot oracle patching")
    ap.add_argument("--max-turns", type=int, default=25,
                    help="max agent turns for --agent repo-patch runs (default 25)")
    ap.add_argument("--level", help="run a named test level (smoke|quick|standard|deep|max) — a "
                    "budget-scaled, reproducible selection + settings; see --list-levels")
    ap.add_argument("--list-levels", action="store_true", help="list available test levels and exit")
    ap.add_argument("--estimate", action="store_true",
                    help="with --level/--models: print a time/data estimate and exit (no run)")
    ap.add_argument("--classify", action="store_true",
                    help="probe --models for capabilities (tools/agentic/reasoner), cache them, and exit")
    ap.add_argument("--import-capabilities", action="store_true",
                    help="pull observed capabilities for --models from the API into the local cache")
    ap.add_argument("--api",
                    default=(os.environ.get("PEAKSTONE_API")
                             or os.environ.get("PEAKSTONE_API_URL")
                             or "https://peakstone.ai/api"),
                    help="API base URL for --import-capabilities (default: the public instance; "
                         "override with --api, $PEAKSTONE_API, or $PEAKSTONE_API_URL for self-hosting)")
    ap.add_argument("--prebuilt", action="store_true",
                    help="for repo-patch: use each instance's prebuilt per-instance Docker image "
                         "(full fidelity) instead of a generic clone+install")
    ap.add_argument("--prune-images", action="store_true",
                    help="with --prebuilt, remove each image after its run (stream one-at-a-time; "
                         "keeps peak disk to ~one image)")
    ap.add_argument("--reference", action="store_true",
                    help="use reference/ solutions instead of calling a model (suite sanity check)")
    ap.add_argument("--no-judge", action="store_true", help="disable LLM judge scoring")
    ap.add_argument("--calibration", action="store_true",
                    help="metacognition probes: ask the model its confidence BEFORE solving and "
                         "whether its own solution is correct AFTER (the calibration axis). Cheap; "
                         "run on a small probe subset, e.g. --level calibration.")
    ap.add_argument("--also", action="append", default=[], metavar="RESULTS_JSON",
                    help="(with --judge-only --bundle) extra results file(s) to merge into the "
                         "re-emitted bundle unfiltered-by-model (e.g. an agentic env-results.json "
                         "— a different axis, appended, never overlaid)")
    ap.add_argument("--judge-only", metavar="PATH",
                    help="re-judge solutions already stored in a prior run's results.json (a "
                         "file, a results dir, or a combined/ dir). Only the judge model needs "
                         "to be loaded — no code is re-generated.")
    ap.add_argument("--judge-model", default=None,
                    help="model name to use as the judge (default: config [judge].model, "
                         "i.e. qwen3-coder)")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="override completion token budget (helps reasoning models finish)")
    ap.add_argument("--gateway", default=None, metavar="URL",
                    help="route ALL generation through a model-swapping gateway (`peakstone serve`) at "
                         "this base URL instead of per-model llama-server ports; the model name in each "
                         "request selects/loads the model. The gateway owns serving — no serve.sh.")
    ap.add_argument("--gateway-key", default=None, metavar="TOKEN",
                    help="bearer token for --gateway (LAN auth); usually unset for a local gateway "
                         "(loopback is exempt).")
    ap.add_argument("--retries", type=int, default=0, metavar="N",
                    help="for tests/both challenges, on test failure feed the error back and let "
                         "the model fix it, up to N extra attempts (default 0 = single-shot). "
                         "Measures self-repair across the whole suite, not just agentic challenges.")
    ap.add_argument("--agents-md", nargs="?", const="__default__", default=None, metavar="FILE",
                    help="apply a global AGENTS.md output contract (system prompt) to all tests/both "
                         "challenges and score a deterministic 'global adherence' axis on each "
                         "(separate from correctness). Bare flag uses the built-in default; pass a "
                         "FILE to override. Helps reasoning models reach a complete answer.")
    ap.add_argument("--config", default=str(paths.config_path()))
    ap.add_argument("--challenges-dir", default=str(paths.challenges_dir()))
    ap.add_argument("--out", default=None)
    ap.add_argument("--bundle", action="store_true",
                    help="also emit a signed, schema-valid Peakstone result bundle (bundle.json) "
                         "next to the report — the reproducible, submittable artifact.")
    ap.add_argument("--stream-output", action="store_true",
                    help="stream live model generation to stdout (token deltas, control-prefixed) so "
                         "the dashboard can show what the model is producing as it solves each task.")
    # planner evaluation (decoupled two-phase: gen plans with planner served, then exec with
    # the fixed coder served). See serve/planner_eval.sh for orchestration.
    ap.add_argument("--gen-plans", metavar="PLANNER",
                    help="phase A: with PLANNER served, write an implementation plan per selected "
                         "challenge to --out (default results/plans-<planner>-<stamp>/).")
    ap.add_argument("--exec-plans", metavar="PLANS_DIR",
                    help="phase B: with the fixed --coder served, implement each plan in PLANS_DIR "
                         "and run tests; rows are tagged mode=planner for the Planner leaderboard.")
    ap.add_argument("--coder", default="qwen3-coder",
                    help="fixed executor model for --exec-plans / --planner (default qwen3-coder).")
    ap.add_argument("--planner", metavar="PLANNER_MODEL",
                    help="planner env type: PLANNER plans each challenge, the fixed --coder executes, "
                         "tests verify. Scored on the planner_score axis. (Single-pass; both served.)")
    ap.add_argument("--env", action="store_true",
                    help="agentic mode: run goal-state-env (multi-machine) challenges with --models "
                         "driving the tool loop until the verifier passes.")
    ap.add_argument("--env-provider", default="auto",
                    help="environment provider for --env: auto|local|docker|microvm (default auto: "
                         "the cheapest that satisfies each challenge's network requirements).")
    args = ap.parse_args(argv)

    if args.update:
        from peakstone.dashboard.update import update_main
        return update_main([])

    # default config = packaged file + the ~/.peakstone overlay (same rule as gateway/api, R31);
    # an explicit --config path is taken verbatim (the caller chose exactly that file)
    cfg = (paths.load_config() if args.config == str(paths.config_path())
           else tomllib.loads(Path(args.config).read_text()))
    host = cfg["server"]["host"]
    # model -> port: serve/models.toml is the source of truth; config [models] can override.
    ports = {}
    try:
        mt = tomllib.loads(paths.models_toml().read_text())
        ports = {name: m["port"] for name, m in mt.items() if "port" in m}
    except Exception:  # noqa: BLE001
        pass
    ports.update(cfg.get("models", {}))
    run_cfg = cfg.get("run", {})
    _freeze_budget(args, run_cfg)   # run identity: one resolved budget for requests + meta + bundle
    jcfg = cfg.get("judge", {})
    judge_model = args.judge_model or jcfg.get("model", "qwen3-coder")
    # global AGENTS.md output contract (--agents-md): appended to the system prompt and scored
    # as a separate adherence axis on tests/both challenges. None = disabled.
    agents_md = global_rules.load_agents_md(args.agents_md) if args.agents_md else None
    tests_system = SYSTEM_PROMPT + ("\n\n" + agents_md if agents_md else "")

    def make_judge_client():
        return _judge_client(args, jcfg, host, ports, judge_model)

    if args.list_levels:
        version, lv = load_levels()
        print(f"Test levels (manifest {version}):")
        for n, l in lv.items():
            flags = "".join(c for c, on in [("J", l.judge), ("A", l.agent), ("P", l.prebuilt)] if on)
            print(f"  {n:9} {l.time_hint:28} [{flags or '-'}]  {l.description}")
        return 0

    if args.estimate:
        if not args.level:
            print("--estimate needs --level", file=sys.stderr); return 2
        from . import estimate as estimate_mod
        for m in (_csv(args.models) or []):
            print(estimate_mod.format_estimate(estimate_mod.estimate(args.level, m)))
        return 0

    if args.classify:
        for m in (_csv(args.models) or []):
            if m not in ports:
                print(f"!! {m} not in registry (serve/models.toml)", file=sys.stderr); continue
            client = LLMClient(f"http://{host}:{ports[m]}")
            if not client.health():
                print(f"!! {m} endpoint not reachable; is serve.sh {m} running?", file=sys.stderr); continue
            print(f"classifying {m} …")
            caps = capabilities.classify(m, client, run_cfg)
            print(f"  probed:    {caps}")
            print(f"  effective: {sorted(capabilities.effective_capabilities(m))}")
        return 0

    if args.import_capabilities:
        import urllib.request
        for m in (_csv(args.models) or []):
            try:
                with urllib.request.urlopen(f"{args.api}/models/{m}", timeout=15) as r:
                    obs = json.load(r).get("observed_capabilities") or []
            except Exception as e:  # noqa: BLE001
                print(f"  {m}: {e}", file=sys.stderr); continue
            if obs:
                capabilities.update_cache(m, {c: True for c in obs}, "observed-api")
            print(f"  {m}: imported {obs}")
        return 0

    if args.judge_only:
        return run_judge_only(args, judge_model, make_judge_client())

    # A bundle is signed + content-addressed to ONE model's identity (file_sha256, sampling, serve_flags)
    # and carries a single run verdict; a multi-model run would mis-attribute the other models' results.
    # Run each model separately (the daemon already queues one model per job).
    if args.bundle and len(_csv(args.models) or []) > 1:
        print("--bundle runs one model at a time (a bundle is signed + attributed to a single model). "
              "Run each model in its own invocation.", file=sys.stderr)
        return 2

    if args.env:
        return run_env_agent(args, host, ports, run_cfg)

    if not args.models and not args.gen_plans and not args.exec_plans:
        print("--models is required (unless using --judge-only/--gen-plans/--exec-plans)",
              file=sys.stderr)
        return 1

    use_judge = jcfg.get("enabled", True) and not args.no_judge and not args.reference

    try:
        paths.require(Path(args.challenges_dir), "challenge corpus")
    except paths.DataNotFound as e:
        print(f"!! {e}", file=sys.stderr)
        return 2
    all_ch = load_challenges(Path(args.challenges_dir))
    # A bare model run (no --level, no targeting filters, not reference/planner) defaults to the
    # official 'standard' level — so it yields a COMPARABLE, submittable bundle (suite=level-standard)
    # rather than an ad-hoc one. Any explicit --level or --ids/--lang/--difficulty/--type/--family/
    # --published-* opts out, as do reference/planner runs.
    _targeted = any([args.ids, args.ids_file, args.lang, args.difficulty, args.type, args.family,
                     args.published_after, args.published_before])
    if not args.level and not _targeted and not (args.reference or args.gen_plans
                                                 or args.exec_plans or args.planner):
        args.level = "standard"
        print("No --level or filters given → defaulting to the official 'standard' level "
              "(comparable + submittable). Use --level smoke|quick for a quicker run, "
              "--no-judge to skip grading, or --ids/--lang/… for an ad-hoc selection.")
    level_meta: dict = {}
    env_chs: list = []   # level-selected goal-state-env challenges (agentic axis; run after coding)
    if args.level:
        version, lvls = load_levels()
        level = lvls.get(args.level)
        if not level:
            print(f"!! unknown level {args.level!r}; run --list-levels", file=sys.stderr)
            return 2
        ordered = resolve_level(level, all_ch)   # manifest axis order (cheap/fast axes first)
        by_id = {c.id: c for c in all_ch}
        chs = [by_id[i] for i in ordered if i in by_id]   # run in manifest order, not filesystem order
        # Env (goal-state) challenges are the kind="env" slice of the same corpus walk (one base +
        # kind, review R28); the level's `family = "env"` axes still resolve separately (resolve_env:
        # ids + id-ordered caps — pinned selection semantics), run through the agent loop after the
        # coding axes and land in the same results list → one bundle scores coding + agentic together.
        if any(sel.get("family") == "env" for sel in level.select) and not args.reference:
            env_by_id = {c.id: c for c in load_challenges(Path(args.challenges_dir), kind="env")}
            env_chs = [env_by_id[i] for i in resolve_env(level, env_by_id.values())
                       if i in env_by_id]
        # apply level settings — explicit CLI flags still win (they only ever turn things ON here).
        if not level.judge:
            use_judge = False
        args.agent = args.agent or level.agent
        args.prebuilt = args.prebuilt or level.prebuilt
        args.calibration = args.calibration or level.calibration
        if level.retries and not args.retries:
            args.retries = level.retries
        level_meta = {"suite_id": f"level-{args.level}", "suite_version": version}
        print(f"Level {args.level}@{version}: {len(chs)} challenges"
              + (f" + {len(env_chs)} env" if env_chs else "")
              + f"  (judge={use_judge} agent={args.agent} prebuilt={args.prebuilt})")
    else:
        ids = list(_csv(args.ids) or [])
        if args.ids_file:
            raw = Path(args.ids_file).read_text().replace(",", "\n")
            ids += [ln.strip() for ln in raw.splitlines() if ln.strip()]
        chs = filter_challenges(
            all_ch,
            langs=_csv(args.lang),
            difficulties=[int(x) for x in _csv(args.difficulty)] if args.difficulty else None,
            ids=ids or None,
            types=_csv(args.type),
            families=_csv(args.family),
            published_after=args.published_after,
            published_before=args.published_before,
        )
    if not chs and not env_chs:
        print("No challenges matched filters.", file=sys.stderr)
        return 1

    if args.gen_plans:
        return run_gen_plans(args, chs, host, ports, run_cfg)
    if args.exec_plans:
        return run_exec_plans(args, chs, host, ports, run_cfg,
                              use_judge, judge_model, make_judge_client() if use_judge else None)
    if args.planner:
        return run_planner(args, chs, host, ports, run_cfg)

    judge_client = make_judge_client() if use_judge else None
    # Judging is optional and judge-LAST by design: a one-GPU box can't hold the bench model and a
    # decent judge at once, so grading normally happens as a separate `--judge-only` pass over the
    # finished run. What must never happen is *silent* degradation — judge/both rows scored
    # tests-only while the output looks judged. Unreachable judge → proceed tests-only, but say so
    # loudly and record the deferral so the bundle can't pass for a judged run.
    judge_deferred = False
    if use_judge and any(ch.scoring in ("judge", "both") for ch in chs):
        if judge_client is None or not judge_client.health():
            where = jcfg.get("base_url") or args.gateway or f"config [models] port for '{judge_model}'"
            print(f"!! judge '{judge_model}' unreachable ({where}) — judge/both rows will be scored "
                  f"tests-only for now.\n"
                  f"!! Grade them afterwards with a judge-last pass: --judge-only <outdir> "
                  f"(recorded in meta.judge_deferred; pass --no-judge to choose tests-only scoring).",
                  file=sys.stderr)
            use_judge, judge_deferred = False, True
    judge_errors = 0   # judge calls that errored mid-run (loud accounting at the end)

    models = _csv(args.models)
    results = []
    # Why each SELECTED challenge produced no row (gated / ctx / abandoned / env-skip). Recorded in
    # the bundle so "selected set" stays the comparable unit while the executed set varies per model.
    skip_reasons: dict[str, str] = {}
    mem_used: dict = {}   # the loaded model's measured footprint (VRAM + host RAM), for the bundle env
    # Non-viability guard: a model stuck in degenerate repetition loops shouldn't grind the whole suite.
    # Skip the rest of a category (family) after this many CONSECUTIVE repetition-loop failures with no
    # pass in it; a category that never produces a pass becomes negative data. If a model passes nothing
    # at all and at least one category was abandoned this way, the whole run is flagged "not_capable".
    loop_skip_streak = int(run_cfg.get("giveup_loop_streak", 3))
    run_passed_any = False
    run_abandoned: list[str] = []   # categories abandoned (in order) across the run — negative data
    print(f"Running {len(models)} model(s) over {len(chs)} challenge(s). "
          f"judge={judge_model if use_judge else False}")

    # When --gateway is set, all models are reached through one swapping gateway (the model name in
    # each request selects/loads it) instead of a per-model llama-server port. One shared client.
    gateway_client = LLMClient(args.gateway, api_key=args.gateway_key or "") if args.gateway else None
    host_load = None if args.reference else _host_load()   # coarse contention snapshot at run start

    for model in models:
        client = None
        model_vram = None
        if not args.reference:
            if gateway_client is not None:
                client = gateway_client
                if not client.health():
                    print(f"!! gateway {args.gateway} not reachable; is `peakstone serve` running?",
                          file=sys.stderr)
                    continue
            else:
                if model not in ports:
                    print(f"!! model '{model}' not in config [models]; skipping", file=sys.stderr)
                    continue
                client = LLMClient(f"http://{host}:{ports[model]}")
                if not client.health():
                    print(f"!! {model} endpoint not reachable; is serve.sh {model} running?",
                          file=sys.stderr)
                    continue
            client.stream = True              # detect/abort repetition loops on every run (not just dashboard)
            client.seed = run_cfg.get("seed")  # fixed seed → reproducible generations (recorded in the bundle)
            if args.stream_output:
                client.on_delta = _emit_gen   # live token stream for the dashboard
                client.on_phase = _emit_phase  # live thinking/answering status
            model_vram = _gpu_mem_used()  # footprint of the one loaded model
            mem_used = {"vram_mib": model_vram, "ram_mib": _server_ram_used()}

        caps = model_capabilities(model)   # gated axes (tools/agentic) this model can attempt
        served_ctx = _served_ctx(model)    # gate long-context challenges this run can't fit
        fam_loop_streak: dict[str, int] = {}   # consecutive repetition-loop fails in each category
        fam_passed: set[str] = set()           # categories that produced at least one pass
        abandoned: set[str] = set()            # categories skipped this model (repetition loops)

        def note_streak(label: str, ch, *, won: bool, looped: bool) -> None:
            """EVERY scoring branch feeds the repetition-loop giveup policy — not just the tests
            path (review R20): a model looping out on math or safety rows burned the same
            wall-clock, and the negative-data verdict should see it."""
            if update_loop_streak(ch.family, won=won, looped=looped, streaks=fam_loop_streak,
                                  passed=fam_passed, abandoned=abandoned,
                                  threshold=loop_skip_streak):
                if ch.family not in run_abandoned:
                    run_abandoned.append(ch.family)
                print(f"{label}  ✗ abandoning category '{ch.family}' "
                      f"({loop_skip_streak} consecutive repetition loops) — skipping the rest")
        ctx = HandlerContext(args=args, run_cfg=run_cfg, client=client, model=model,
                             model_vram=model_vram, tests_system=tests_system,
                             agents_md=agents_md, use_judge=use_judge,
                             judge_client=judge_client, judge_model=judge_model)
        for ch in chs:
            label = f"{model:>18} | {ch.id:<28}"
            if ch.family in abandoned:         # category given up on after a repetition-loop streak
                print(f"{label}  SKIP (category '{ch.family}' abandoned — repetition loops)")
                skip_reasons[ch.id] = "category-abandoned (repetition loops)"
                continue
            print(f"{label}  → solving [{ch.scoring}] …")   # live progress: what's running now

            if not relevant(ch.family, caps):
                print(f"{label}  SKIP (model lacks '{GATED_CAP.get(ch.family)}')")
                skip_reasons[ch.id] = f"gated: model lacks '{GATED_CAP.get(ch.family)}'"
                continue
            if ch.min_ctx and served_ctx is not None and ch.min_ctx > served_ctx:
                print(f"{label}  SKIP (needs ctx {ch.min_ctx}, served {served_ctx})")
                skip_reasons[ch.id] = f"ctx: needs {ch.min_ctx}, served {served_ctx}"
                continue

            out = handler_for(ch)(ctx, ch, label)
            if out.skip is not None:
                skip_reasons[ch.id] = out.skip
            if out.row is not None:
                results.append(out.row)
            if out.won is not None:   # this scoring mode feeds the giveup policy (review R20)
                if out.won:
                    run_passed_any = True
                note_streak(label, ch, won=out.won, looped=out.looped)

        # Agentic axis: the level's goal-state-env challenges, run last (slowest — a multi-turn
        # agent loop per challenge); see handlers.run_env_axis.
        if env_chs and client is not None:
            if run_env_axis(ctx, env_chs, caps, results, skip_reasons):
                run_passed_any = True
        judge_errors += ctx.judge_errors   # judge calls that flaked, accumulated across models

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "results" / stamp
    meta = {
        "timestamp": stamp, "models": models, "n_challenges": len(chs) + len(env_chs),
        "judge": (judge_model if use_judge else None),
        "sandbox": effective_sandbox(run_cfg.get("sandbox")), "reference": args.reference,
        "gpu": _gpu_info(), "retries": args.retries,
        "agents_md": bool(agents_md), "mem_used": mem_used, "host_load": host_load,
        # the run's generation budget (run identity) — the SAME resolved numbers every request used
        "max_tokens": run_cfg["max_tokens"],
        "max_tokens_reasoning": run_cfg["max_tokens_reasoning"],
        "gateway": bool(args.gateway),
        # The SELECTED set (level-pinned, pre-gating) — the comparable unit the bundle's suite
        # content_hash is computed over; skip_reasons explains selected-but-not-executed ids.
        "selected_ids": [c.id for c in chs] + [c.id for c in env_chs],
        "skip_reasons": skip_reasons,
        **level_meta,
    }
    if judge_deferred:
        meta["judge_deferred"] = True   # judge/both rows are tests-only until a --judge-only pass
    if judge_errors:
        # Loud, and recorded: these rows silently degraded to tests-only scoring (scoring.py falls
        # back when the judge didn't run), so the run is NOT compliant with a judge=true level.
        meta["judge_errors"] = judge_errors
        print(f"!! {judge_errors} judge call(s) errored — affected judge/both rows were scored "
              f"tests-only; grade them with a --judge-only pass (recorded in meta.judge_errors)",
              file=sys.stderr)
    # Negative data: categories abandoned to repetition loops, and a run-level verdict when the model
    # never passed anything yet looped out of a category — i.e. this (quant, ctx, reasoning) config is
    # not worth testing. Recorded in the bundle and faceted on the leaderboard.
    if run_abandoned:
        meta["abandoned_categories"] = run_abandoned
        # A pass in ANY scoring branch (math/tools/safety/agentic — not just the tests path that sets
        # run_passed_any inline) means this config is worth testing; don't brand it not_capable.
        run_passed_any = run_passed_any or any((r.get("final_score") or 0) > 0 for r in results)
        if not run_passed_any and not args.reference:
            meta["run_status"] = "not_capable"
            meta["run_verdict"] = {"reason": "repetition_loops",
                                   "abandoned_categories": run_abandoned,
                                   "loop_streak": loop_skip_streak}
    write_report(results, outdir, meta)
    print(f"\nReport: {outdir / 'leaderboard.md'}")
    if not args.reference:   # refine each model's capability cache from what it demonstrated (positives)
        for m in models:
            obs = capabilities.observe([r for r in results if r.get("model") == m])
            if obs:
                capabilities.update_cache(m, obs, "observed")
    if args.bundle and not args.reference:
        _emit_bundle(meta, results, outdir)
    return 0


def run_planner(args, chs, host, ports, run_cfg):
    """Planner env type: PLANNER plans each challenge, the fixed --coder executes, tests verify.
    Emits planner-category rows scored on the planner_score axis (the same coder isolates the plan)."""
    from .env.planner import planner_result_row, run_planner_task
    planner = args.planner
    coder = args.coder
    planner_client = _model_client(host, ports, planner)
    coder_client = _model_client(host, ports, coder)
    if planner_client is None or coder_client is None:
        return 1
    results = []
    print(f"Planner eval: {planner} plans, {coder} executes, over {len(chs)} challenge(s).")
    for ch in chs:
        if ch.scoring not in ("tests", "both"):   # need executable tests to score the plan
            continue
        res = run_planner_task(planner_client, planner, coder_client, coder, ch, run_cfg)
        results.append(planner_result_row(ch, res, planner))
        flag = "ok " if res["passed"] else "   "
        print(f"  {planner}  {flag} {ch.id}  downstream={res['final_score']:.2f} "
              f"({res['passed_n']}/{res['total']})  plan={res['plan_chars']}ch")
    if not results:
        print("No planner results produced.", file=sys.stderr)
        return 1
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "results" / f"planner-{planner}-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    avg = sum(r["final_score"] for r in results) / len(results)
    meta = {"timestamp": stamp, "models": [planner], "n_challenges": len(results), "judge": None,
            "sandbox": effective_sandbox(run_cfg.get("sandbox")), "reference": False,
            "gpu": _gpu_info(), "coder_model": coder, "max_tokens": run_cfg.get("max_tokens")}
    print(f"\nPlanner {planner} (coder {coder}): mean downstream {avg:.3f} over {len(results)} tasks. "
          f"-> {outdir}")
    if args.bundle:
        _emit_bundle(meta, results, outdir)
    return 0


def run_env_agent(args, host, ports, run_cfg):
    """Agentic run mode: the model drives a multi-node environment (tool loop) until the goal-state
    verifier passes. Emits goal-state-env result rows that flow to the leaderboard like coding runs."""
    from .env import env_result_row
    from .env.agent import run_env_task
    from .env.firecracker import UnsupportedHost

    models = _csv(args.models)
    if not models:
        print("--env needs --models <model>", file=sys.stderr)
        return 1
    chs = load_challenges(Path(args.challenges_dir), kind="env")
    if args.ids:
        wanted = set(_csv(args.ids))
        chs = [c for c in chs if c.id in wanted]
    if not chs:
        print("No goal-state-env challenges found (challenges/env/*/).", file=sys.stderr)
        return 1

    results = []
    print(f"Agentic run: {len(models)} model(s) over {len(chs)} env challenge(s).")
    for model in models:
        client = _model_client(host, ports, model)
        if client is None:
            continue
        for ch in chs:
            prov = _select_env_provider(args, ch)
            if prov is None:
                print(f"  {model}  --  {ch.id}: no isolating env provider available (start docker, "
                      f"or consent to host execution: --env-provider local / PEAKSTONE_ALLOW_LOCAL_ENV=1)")
                continue
            try:
                res = run_env_task(client, model, ch, prov)
            except (UnsupportedHost, RuntimeError) as e:
                print(f"  {model}  --  {ch.id}: provider error: {e}")
                continue
            except Exception as e:  # noqa: BLE001 — one broken challenge must not nuke the whole run
                print(f"  {model}  --  {ch.id}: {type(e).__name__}: {e}")
                continue
            results.append(env_result_row(ch, res, model=model,
                                          turns_to_green=res.get("turns_to_green"),
                                          turns_used=res.get("turns_used"),
                                          transcript=res.get("transcript", "")))
            flag = "ok " if res["passed"] else "   "
            print(f"  {model}  {flag} {ch.id} [{prov.name}]  passed={res['passed']} "
                  f"turns={res.get('turns_used')} green@{res.get('turns_to_green')}")

    if not results:
        print("No env results produced.", file=sys.stderr)
        return 1
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "results" / f"env-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "env-results.json").write_text(json.dumps(results, indent=2))
    meta = {"timestamp": stamp, "models": models, "n_challenges": len(chs),
            "judge": None, "sandbox": "env", "reference": False, "gpu": _gpu_info(),
            "max_tokens": run_cfg.get("max_tokens")}
    print(f"\n{sum(1 for r in results if r['final_score'] >= 0.999)}/{len(results)} reached goal state. "
          f"Results: {outdir / 'env-results.json'}")
    if args.bundle:
        _emit_bundle(meta, results, outdir)
    return 0


def _emit_bundle(meta, results, outdir):
    """Produce + write a signed result bundle next to the report (best-effort; never fails a run)."""
    try:
        from . import bundle as _bundle
        b = _bundle.produce_bundle(meta, results)
        path = _bundle.write_bundle(b, Path(outdir) / "bundle.json")
        n_det = sum(1 for r in b["results"] if r["verification"] == "deterministic-tests")
        print(f"Bundle: {path}  ({len(b['results'])} results, {n_det} deterministic, "
              f"signed by {b['submitter']['pubkey'][:12]}…)")
    except Exception as e:  # noqa: BLE001
        print(f"!! bundle not written: {type(e).__name__}: {e}", file=sys.stderr)


def _load_results(path: Path) -> list[dict]:
    """Load result rows from a results.json file, a run dir, a combined/ dir, or a dir of
    per-model */results.json files."""
    if path.is_file():
        return json.loads(path.read_text()).get("results", [])
    for c in (path / "results.json", path / "combined" / "results.json"):
        if c.exists():
            return json.loads(c.read_text()).get("results", [])
    rows: list[dict] = []
    for f in sorted(path.glob("*/results.json")):
        rows.extend(json.loads(f.read_text()).get("results", []))
    return rows


def _load_run_meta(path: Path) -> dict:
    """The ORIGINAL run's meta (suite id/version, budget, gpu, selected set …) from its
    results.json — the judged re-emitted bundle must describe the GENERATION run's identity,
    with only the judge fields layered on top."""
    if path.is_file():
        return json.loads(path.read_text()).get("meta") or {}
    for c in (path / "results.json", path / "combined" / "results.json"):
        if c.exists():
            return json.loads(c.read_text()).get("meta") or {}
    return {}


def run_judge_only(args, judge_model, judge_client) -> int:
    """Re-judge already-generated solutions stored in a prior run, loading only the judge."""
    if judge_client is None:
        return 1
    src = Path(args.judge_only)
    rows = _load_results(src)
    if not rows:
        print(f"No results found under {src}", file=sys.stderr)
        return 1
    if not judge_client.health():
        print(f"!! judge model '{judge_model}' endpoint not reachable; "
              f"is serve.sh {judge_model} running?", file=sys.stderr)
        return 1

    chmap = {c.id: c for c in load_challenges(Path(args.challenges_dir))}
    langs = _csv(args.lang)
    diffs = [int(x) for x in _csv(args.difficulty)] if args.difficulty else None
    ids = _csv(args.ids)
    only_models = _csv(args.models)

    # --level: re-stamp to the CURRENT level selection (repack-style, honest subset — challenges
    # the run never did just stay absent and are documented as skipped). Filtering happens BEFORE
    # judging so the judge only grades rows that will ship, and the re-emitted bundle carries the
    # level's selected_ids → the selected-set suite hash, comparable across models (R4).
    level_ids: list[str] | None = None
    level_version = None
    if args.level:
        from .env import load_env_challenges
        from .levels import load_levels, resolve, resolve_env
        level_version, levels = load_levels()
        if args.level not in levels:
            print(f"!! unknown level '{args.level}'", file=sys.stderr)
            return 1
        lv = levels[args.level]
        code_ids = list(resolve(lv, chmap.values()))
        env_ids = [i for i in resolve_env(lv, load_env_challenges(Path(args.challenges_dir)))
                   if i not in set(code_ids)]
        level_ids = code_ids + env_ids
        keep = set(level_ids)
        before = len(rows)
        rows = [r for r in rows if r.get("challenge") in keep]
        print(f"Level {args.level}@{level_version}: kept {len(rows)}/{before} stored rows "
              f"in the current selection ({len(level_ids)} ids)")

    print(f"Judge-only: judging up to {len(rows)} solution(s) with '{judge_model}'.")
    judged = 0
    for r in rows:
        if only_models and r["model"] not in only_models:
            continue
        if langs and r["language"] not in langs:
            continue
        if diffs and r["difficulty"] not in diffs:
            continue
        if ids and r["challenge"] not in ids:
            continue
        ch = chmap.get(r["challenge"])
        resp = r.get("response") or ""
        if ch is None or not resp or resp.startswith("(reference") or r.get("note") == "error":
            continue
        files = extract_files(resp, ch.solution_file, ch.language)
        if not files:
            continue
        sol_text = "\n\n".join(f"// {p}\n{c}" for p, c in files.items())
        summary = f"{r.get('passed', 0)}/{r.get('total', 0)} tests passed"
        jr = judge_solution(judge_client, judge_model, ch, sol_text, summary)
        r["judge_detail"] = jr
        r["judge_score"] = jr.get("normalized", 0.0)
        if jr.get("error") or not jr.get("scores"):
            # judge flaked (timeout / unparseable) — don't fold a spurious 0.0 into final_score;
            # leave the test-based score from the run untouched (see scoring._judge_ran)
            continue
        # fold judge into final only for judge/both; tests-scored challenges keep their score
        if ch.scoring == "judge":
            r["final_score"] = round(jr.get("normalized", 0.0), 3)
        elif ch.scoring == "both":
            w = ch.judge_weight
            r["final_score"] = round((1 - w) * r.get("test_score", 0.0)
                                     + w * jr.get("normalized", 0.0), 3)
        judged += 1
        print(f"  {r['model']:>18} | {r['challenge']:<26} "
              f"quality={r['judge_score']:.2f} {jr.get('scores', {})}")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    # write next to the run, not nested inside combined/: <run>/judged-<judge>-<stamp>/
    if src.is_file():
        base = src.parent
    elif src.name == "combined":
        base = src.parent
    else:
        base = src
    outdir = Path(args.out) if args.out else base / f"judged-{judge_model}-{stamp}"
    meta = {
        "timestamp": stamp, "models": sorted({r["model"] for r in rows}),
        "n_challenges": len({r["challenge"] for r in rows}),
        "judge": judge_model, "sandbox": "judge-only", "judged": judged,
        "gpu": _gpu_info(),
    }
    write_report(rows, outdir, meta)
    print(f"\nJudged {judged} solutions. Report: {outdir / 'leaderboard.md'}")

    if args.bundle:
        # Judge-LAST bundling: re-emit the run's signed bundle with the judge scores folded in.
        # The bundle keeps the GENERATION run's identity (its meta: suite, budget, gpu, selected
        # set) — only the judge fields are layered on: meta.judge names the grader, and every
        # judged row carries {model, scores, temperature, max_tokens} so how the board was graded
        # is part of the record. This is what the daemon submits for judge=true levels.
        from .judge import JUDGE_MAX_TOKENS, JUDGE_TEMPERATURE
        orig_meta = _load_run_meta(src)
        if not orig_meta:
            print("!! --bundle: no meta found in the source run (results.json) — bundle not "
                  "written (report above is still valid)", file=sys.stderr)
            return 1
        brows = list(rows)
        # --also: merge extra results (e.g. the model's agentic env-results.json — a different
        # axis) by APPEND only, never replacing a base row; --level's selection filter applies.
        for extra in (args.also or []):
            ed = json.loads(Path(extra).read_text())
            erows = ed["results"] if isinstance(ed, dict) else ed
            have = {r.get("challenge") for r in brows}
            fresh = [r for r in erows if r.get("challenge") not in have
                     and (level_ids is None or r.get("challenge") in set(level_ids))]
            brows += fresh
            print(f"  + {len(fresh)} row(s) merged from {extra}")
        if len({r["model"] for r in brows}) > 1:
            print("!! --bundle: the merged rows span multiple models; a bundle is signed for "
                  "ONE model — judge each run dir separately", file=sys.stderr)
            return 1
        bmeta = {**orig_meta, "judge": judge_model, "judged": judged,
                 "judge_params": {"temperature": JUDGE_TEMPERATURE, "max_tokens": JUDGE_MAX_TOKENS}}
        if args.level:
            # re-stamp to the current manifest + record the selection, so the bundle carries the
            # model-independent selected-set suite hash and documents what wasn't run (R4)
            bmeta.update(suite_id=f"level-{args.level}", suite_version=level_version,
                         selected_ids=level_ids)
            bmeta.pop("skip_reasons", None)   # the original run's reasons predate this selection
        _emit_bundle(bmeta, brows, outdir)
    return 0


def _model_client(host, ports, model):
    """An LLMClient for a served model, or None (with a message) if missing/unreachable."""
    if model not in ports:
        print(f"!! model '{model}' not in serve/models.toml or config [models]", file=sys.stderr)
        return None
    client = LLMClient(f"http://{host}:{ports[model]}")
    if not client.health():
        print(f"!! {model} endpoint not reachable; is it served?", file=sys.stderr)
        return None
    return client


def run_gen_plans(args, chs, host, ports, run_cfg):
    """Planner-eval phase A: with the planner served, write one implementation plan per challenge."""
    planner = args.gen_plans
    client = _model_client(host, ports, planner)
    if client is None:
        return 1
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "results" / f"plans-{planner}-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"planner": planner, "stamp": stamp, "plans": {}}
    print(f"Generating plans with '{planner}' over {len(chs)} challenge(s) -> {outdir}")
    for ch in chs:
        res = client.chat(planner,
                          [{"role": "system", "content": PLAN_SYSTEM},
                           {"role": "user", "content": ch.spec}],
                          temperature=run_cfg.get("temperature", 0.2),
                          max_tokens=_budget(args, run_cfg),
                          timeout=run_cfg.get("request_timeout", 600))
        if res.error:
            print(f"{planner:>18} | {ch.id:<28}  PLAN ERROR {res.error[:60]}")
            continue
        # strip the planner's <think> monologue so only the actual plan reaches the coder
        plan = global_rules.strip_think(res.text)
        (outdir / f"{ch.id}.md").write_text(plan)
        manifest["plans"][ch.id] = {
            "latency_s": res.latency_s, "tok_per_s": res.tok_per_s,
            "plan_chars": len(plan), "completion_tokens": res.completion_tokens,
        }
        print(f"{planner:>18} | {ch.id:<28}  ok  plan {len(plan)}c "
              f"{(res.latency_s or 0):.1f}s")
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nPlans: {outdir}")
    return 0


def run_exec_plans(args, chs, host, ports, run_cfg, use_judge, judge_model, judge_client):
    """Planner-eval phase B: with the fixed coder served, implement each stored plan and test it.

    Rows are keyed by the PLANNER (so the Planner leaderboard ranks planners) and tagged
    mode="planner" with the executor recorded in coder_model.
    """
    plans_dir = Path(args.exec_plans)
    mf = plans_dir / "manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {"planner": plans_dir.name, "plans": {}}
    planner = manifest.get("planner", plans_dir.name)
    coder = args.coder
    client = _model_client(host, ports, coder)
    if client is None:
        return 1
    model_vram = _gpu_mem_used()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else ROOT / "results" / f"planner-{planner}-{stamp}"
    results = []
    print(f"Executing '{planner}' plans with fixed coder '{coder}' -> {outdir}")
    for ch in chs:
        plan_file = plans_dir / f"{ch.id}.md"
        if not plan_file.exists():
            continue
        plan = plan_file.read_text()
        label = f"{planner:>16}/{coder} | {ch.id:<22}"
        user = ch.spec + "\n\n## Implementation plan (follow this)\n\n" + plan
        res = client.chat(coder,
                          [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": user}],
                          temperature=run_cfg.get("temperature", 0.2),
                          max_tokens=_budget(args, run_cfg),
                          timeout=run_cfg.get("request_timeout", 600))
        if res.error:
            print(f"{label}  ERROR {res.error[:60]}")
            continue
        files = extract_files(res.text, ch.solution_file, ch.language)
        run = run_tests(ch, files, run_cfg)
        judge_res = None
        if use_judge and ch.scoring in ("judge", "both"):
            summary = f"{run.passed}/{run.total} tests passed (rc={run.returncode})"
            sol_text = "\n\n".join(f"// {p}\n{c}" for p, c in files.items())
            judge_res = judge_solution(judge_client, judge_model, ch, sol_text, summary)
        sc = compute_score(ch, run, judge_res)
        pdata = manifest.get("plans", {}).get(ch.id, {})
        extra = {
            "mode": "planner", "planner_model": planner, "coder_model": coder,
            "planner_latency_s": pdata.get("latency_s"), "plan_chars": pdata.get("plan_chars"),
            "planner_response": plan,
        }
        if getattr(run, "metrics", None):
            extra["metrics"] = run.metrics
        results.append(_row(planner, ch, run, sc, judge_res, response=res.text,
                            tps=res.tok_per_s, lat=res.latency_s, ptoks=res.prompt_tokens,
                            ctoks=res.completion_tokens, rtoks=res.reasoning_tokens,
                            vram=model_vram, extra=extra))
        print(f"{label}  {'ok ' if run.ok else '   '} final={sc['final_score']:.2f} "
              f"tests={sc['passed']}/{sc['total']}")
    meta = {
        "timestamp": stamp, "models": [planner], "n_challenges": len(results),
        "judge": (judge_model if use_judge else None),
        "sandbox": effective_sandbox(run_cfg.get("sandbox")), "reference": False,
        "gpu": _gpu_info(), "retries": 0, "agents_md": False,
        "mode": "planner", "planner_model": planner, "coder_model": coder,
        "max_tokens": run_cfg.get("max_tokens"),
    }
    write_report(results, outdir, meta)
    print(f"\nReport: {outdir / 'leaderboard.md'}")
    if args.bundle:
        _emit_bundle(meta, results, outdir)
    return 0


def _served_ctx(model: str) -> int | None:
    """The context window this run serves `model` at: PEAKSTONE_CTX overrides the registry ctx.
    Used to gate long-context challenges a model can't fit (avoids unfair truncation failures)."""
    ov = os.environ.get("PEAKSTONE_CTX")
    if ov and ov.isdigit():
        return int(ov)
    ctx = capabilities._model_cfg(model).get("ctx")
    return int(ctx) if isinstance(ctx, int) else None


def _install_pipe_safety() -> None:
    """A crashed/killed viewer (the TUI) breaking our stdout pipe must NOT lose the run. Installed
    at the top of main() so EVERY entry point gets it — the `peakstone bench` console script used
    to bypass the __main__-only wrap and die on the first broken-pipe write (review R20)."""
    if not isinstance(sys.stdout, _PipeSafe):
        sys.stdout = _PipeSafe(sys.stdout)
    if not isinstance(sys.stderr, _PipeSafe):
        sys.stderr = _PipeSafe(sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
