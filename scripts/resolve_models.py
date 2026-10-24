#!/usr/bin/env python3
"""Discover models without inference; resolve roles from provider metadata.

This selects a plan, never executes a task or changes the active session.
Catalog descriptions are data, never instructions. No credentials are read.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".codex" / "state" / "stage-model-dispatch"
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
NEW_MODEL_WINDOW = 7 * 86400


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".dispatch-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def discover(timeout=20, command=None):
    """Only initialize and paginated model/list; no thread or turn is started."""
    process = subprocess.Popen(
        command or ["codex", "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
    )
    incoming = queue.Queue()

    def reader():
        for line in process.stdout:
            try:
                incoming.put(json.loads(line))
            except ValueError:
                continue
        incoming.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout

    def send(method, params, ident=None):
        value = {"method": method, "params": params}
        if ident is not None:
            value["id"] = ident
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def receive(ident):
        while True:
            try:
                value = incoming.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("model discovery timed out") from None
            if value is None:
                raise RuntimeError("model discovery connection closed")
            if value.get("id") == ident:
                if "error" in value:
                    raise RuntimeError("model discovery RPC rejected")
                return value["result"]
            if time.monotonic() >= deadline:
                raise RuntimeError("model discovery timed out")

    try:
        send("initialize", {"clientInfo": {"name": "stage_model_dispatch", "version": "1"}}, 1)
        receive(1)
        send("initialized", {})
        models, cursor, seen = [], None, set()
        for ident in range(2, 102):
            send("model/list", {"includeHidden": False, "limit": 100, "cursor": cursor}, ident)
            result = receive(ident)
            models.extend(result["data"])
            cursor = result.get("nextCursor")
            if not cursor:
                return {"data": models}
            if cursor in seen:
                raise RuntimeError("model discovery pagination loop")
            seen.add(cursor)
        raise RuntimeError("model discovery pagination limit")
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        process.stdin.close()
        thread.join(timeout=2)
        process.stdout.close()


def normalize(catalog):
    """Accept app-server or the active tool's equivalent metadata projection."""
    rows = catalog.get("data", [])
    models = []
    for row in rows:
        model = row.get("model") or row.get("id")
        if row.get("hidden") or not isinstance(model, str) or not re.fullmatch(r"[\w.:-]+", model):
            continue
        efforts = [x["reasoningEffort"] for x in row.get("supportedReasoningEfforts", [])
                   if isinstance(x, dict) and isinstance(x.get("reasoningEffort"), str)]
        if not efforts:
            continue
        models.append({
            "model": model, "description": str(row.get("description", "")),
            "specialty": str(row.get("modelSpecialty") or ""),
            "efforts": efforts, "default_effort": row.get("defaultReasoningEffort"),
            "default": bool(row.get("isDefault")),
            "modalities": row.get("inputModalities", ["text"]),
            "upgrade": row.get("upgrade") or (row.get("upgradeInfo") or {}).get("model"),
        })
    if not models:
        raise ValueError("no usable models in catalog")
    return models


def get_catalog(state, refresh=False, ttl=86400, discovery=discover):
    path = state / "catalog.json"
    cached = None
    try:
        cached = read_json(path)
        normalize(cached["catalog"])
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    age = time.time() - cached["fetched_at"] if cached else float("inf")
    if cached and 0 <= age < ttl and not refresh:
        return cached["catalog"], "cache", []
    try:
        catalog = discovery()
        normalize(catalog)
        write_json(path, {"fetched_at": time.time(), "catalog": catalog})
        return catalog, "model/list", []
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        if cached:
            return cached["catalog"], "stale_cache", ["discovery failed; using cached models: " + type(exc).__name__]
        raise RuntimeError("model discovery unavailable and no usable cache") from exc


def new_models(state, models, window=NEW_MODEL_WINDOW):
    """Return models first listed within the window. The first run is the baseline."""
    path = state / "seen.json"
    try:
        seen = read_json(path)
    except (OSError, ValueError):
        seen = None
    now = time.time()
    first = now if seen is not None else 0
    seen = seen or {}
    added = {m["model"]: first for m in models if m["model"] not in seen}
    if added:
        seen.update(added)
        write_json(path, seen)
    return [m["model"] for m in models if now - seen[m["model"]] < window]


def effort_for(model, requested):
    supported = model["efforts"]
    if requested in supported:
        return requested
    # 'ultra' may add delegation/cost semantics. Never opt in by accident.
    ceiling = len(EFFORTS) - 1 if requested == "deep" else EFFORTS.index(requested)
    for effort in reversed(EFFORTS[:ceiling + 1]):
        if effort in supported:
            return effort
    # Successors may drop the lower effort tiers. Use the nearest supported
    # general tier above the default, but never unknown/automatic-agent modes.
    for effort in EFFORTS[ceiling + 1:]:
        if effort in supported:
            return effort
    raise ValueError("no compatible reasoning effort for " + model["model"])


def choose(models, role_policy, excluded=(), pin=None, last_good=None, recovery=False, modality="text"):
    eligible = [m for m in models if m["model"] not in excluded and modality in m["modalities"]]
    if pin:
        eligible = [m for m in eligible if m["model"] == pin]
    compatible = []
    for m in eligible:
        try:
            compatible.append((m, effort_for(m, role_policy["effort"])))
        except ValueError:
            pass
    if not compatible:
        raise ValueError("no compatible model; explicit pins are never silently replaced")
    ids = {m["model"] for m, _ in compatible}

    def score(item):
        m, _ = item
        description = (m["description"] + " " + m["specialty"]).lower()
        matches = sum(bool(re.search(r"\b" + re.escape(s.lower()) + r"\b", description))
                      for s in role_policy["signals"])
        return (int(recovery and m["model"] == last_good),
                int(not m["upgrade"] or m["upgrade"] not in ids), matches, int(m["default"]))

    # Equal matches retain provider order, never sort version-like names.
    model, effort = max(compatible, key=score)
    return {"model": model["model"], "effort": effort,
            "reason": "last successful model" if recovery and model["model"] == last_good else "role signals, upgrade metadata, provider order",
            "effort_adjusted": role_policy["effort"] not in (effort, "deep"),
            "runtime_identity": "unverified until execution"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "catalog", "record-success", "record-failure"])
    parser.add_argument("--state-dir", type=Path, default=STATE)
    parser.add_argument("--catalog", type=Path, help="Active tool metadata in app-server data format; no network")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--role")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--modality", default="text")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    policy = read_json(ROOT / "routing.json")
    state_path = args.state_dir / "health.json"
    try:
        health = read_json(state_path)
    except (OSError, ValueError):
        health = {"last_good": {}, "blocked_until": {}}
    try:
        if args.command.startswith("record-"):
            if args.role not in policy["codex_roles"] or not args.model:
                raise ValueError("record requires a valid --role and concrete --model")
            if args.command == "record-success":
                health["last_good"][args.role] = args.model
                health["blocked_until"].pop(args.model, None)
            else:
                health["blocked_until"][args.model] = time.time() + 3600
            write_json(state_path, health)
            result = {"recorded": args.command, "model": args.model}
        else:
            if args.catalog:
                catalog, source, warnings = read_json(args.catalog), "explicit_runtime_catalog", []
            else:
                catalog, source, warnings = get_catalog(args.state_dir, args.refresh, policy["cache_ttl_seconds"])
            models = normalize(catalog)
            result = {"source": source, "warnings": warnings, "models": models}
            if args.command == "plan":
                if args.model and not args.role:
                    raise ValueError("--model pin requires --role")
                roles = [args.role] if args.role else list(policy["codex_roles"])
                if any(role not in policy["codex_roles"] for role in roles):
                    raise ValueError("unknown role")
                excluded = set(args.exclude) | {m for m, t in health["blocked_until"].items() if t > time.time()}
                if args.effort:
                    # Explicit user choices are exact, unlike default policies.
                    models = [m for m in models if args.effort in m["efforts"]]
                result["roles"] = {}
                for role in roles:
                    rp = dict(policy["codex_roles"][role])
                    if args.effort:
                        rp["effort"] = args.effort
                    normal = choose(models, rp, pin=args.model, modality=args.modality)
                    result["roles"][role] = choose(models, rp, excluded, args.model,
                        health["last_good"].get(role), normal["model"] in excluded, args.modality)
                # A full plan that ignores a newly listed model usually means the
                # provider's wording no longer matches routing.json signals.
                if not args.catalog and not args.role:
                    picked = {r["model"] for r in result["roles"].values()}
                    for name in new_models(args.state_dir, models):
                        if name not in picked:
                            warning = ("new model " + name + " is not selected for any role;"
                                       " check routing.json signals or pin it with --role/--model")
                            warnings.append(warning)
                            print("dispatch warning: " + warning, file=sys.stderr)
                result["frozen_at"] = time.time()
            if args.output:
                write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, "dispatch: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
