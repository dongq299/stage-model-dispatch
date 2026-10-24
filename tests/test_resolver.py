import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("resolver", ROOT / "scripts/resolve_models.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def row(name, description="Workhorse coding model", efforts=("low", "medium", "high"), **kw):
    return {"model": name, "description": description, "supportedReasoningEfforts":
            [{"reasoningEffort": e} for e in efforts], **kw}


class ResolverTests(unittest.TestCase):
    policy = {"signals": ["workhorse", "coding"], "effort": "high"}

    def choose(self, rows, **kw):
        return m.choose(m.normalize({"data": rows}), self.policy, **kw)

    def test_new_generation_without_policy_edit(self):
        self.assertEqual(self.choose([row("new-name"), row("old-name")])["model"], "new-name")

    def test_version_numbers_do_not_override_provider_order(self):
        self.assertEqual(self.choose([row("small-version-2"), row("big-version-999")])["model"], "small-version-2")

    def test_role_fit_over_provider_default(self):
        rows = [row("frontier", "Most demanding reasoning", isDefault=True), row("coder")]
        self.assertEqual(self.choose(rows)["model"], "coder")

    def test_official_upgrade_replaces_retiring_model(self):
        self.assertEqual(self.choose([row("old", upgrade="new"), row("new")])["model"], "new")

    def test_hidden_and_incompatible_models_not_selected(self):
        self.assertEqual(self.choose([row("hidden", hidden=True), row("unsupported", efforts=("future",)), row("ok")])["model"], "ok")

    def test_deep_does_not_enable_ultra(self):
        model = m.normalize({"data": [row("a", efforts=("high", "max", "ultra"))]})[0]
        self.assertEqual(m.effort_for(model, "deep"), "max")

    def test_default_effort_adjustment_reported(self):
        result = self.choose([row("a", efforts=("low", "medium"))])
        self.assertEqual(result["effort"], "medium")
        self.assertTrue(result["effort_adjusted"])

    def test_successor_with_only_higher_efforts(self):
        result = self.choose([row("successor", efforts=("xhigh", "max", "ultra"))])
        self.assertEqual(result["effort"], "xhigh")
        self.assertTrue(result["effort_adjusted"])

    def test_pin_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):
            self.choose([row("a")], pin="missing")

    def test_recovery_prefers_last_success_over_new_candidate(self):
        result = self.choose([row("new"), row("middle"), row("last-good")], excluded=["new"], last_good="last-good", recovery=True)
        self.assertEqual(result["model"], "last-good")

    def test_last_good_not_sticky_during_normal_upgrade(self):
        self.assertEqual(self.choose([row("new"), row("old")], last_good="old")["model"], "new")

    def test_modality_filter(self):
        self.assertEqual(self.choose([row("text", inputModalities=["text"]), row("vision", inputModalities=["text", "image"])], modality="image")["model"], "vision")

    def test_cache_refresh_and_offline_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            catalog = {"data": [row("new")]}
            _, source, _ = m.get_catalog(state, discovery=lambda: catalog)
            self.assertEqual(source, "model/list")
            def failure():
                raise RuntimeError("offline")
            self.assertEqual(m.get_catalog(state, discovery=failure)[1], "cache")
            result = m.get_catalog(state, refresh=True, discovery=failure)
            self.assertEqual(result[1], "stale_cache")
            self.assertTrue(result[2])

    def test_no_catalog_never_invents_model(self):
        with tempfile.TemporaryDirectory() as d:
            def failure():
                raise RuntimeError("offline")
            with self.assertRaises(RuntimeError):
                m.get_catalog(Path(d), discovery=failure)

    def test_cli_explicit_catalog_and_health_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            cat = Path(d) / "models.json"
            cat.write_text(json.dumps({"data": [row("new"), row("old")]}))
            base = [sys.executable, str(ROOT / "scripts/resolve_models.py")]
            def call(*args):
                return subprocess.run(base + list(args) + ["--state-dir", d], text=True, capture_output=True)
            self.assertEqual(call("record-success", "--role", "implementation", "--model", "old").returncode, 0)
            self.assertEqual(call("record-failure", "--role", "implementation", "--model", "new").returncode, 0)
            result = call("plan", "--catalog", str(cat), "--role", "implementation")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["roles"]["implementation"]["model"], "old")
            unsupported = call("plan", "--catalog", str(cat), "--role", "implementation", "--effort", "max")
            self.assertNotEqual(unsupported.returncode, 0)

    def test_unrelated_block_does_not_stop_upgrade(self):
        with tempfile.TemporaryDirectory() as d:
            cat = Path(d) / "models.json"
            cat.write_text(json.dumps({"data": [row("new-coder"), row("old-coder"), row("research", "fast affordable")]}))
            m.write_json(Path(d)/"health.json", {"last_good": {"implementation": "old-coder"}, "blocked_until": {"research": time.time()+60}})
            result = subprocess.run([sys.executable, str(ROOT / "scripts/resolve_models.py"), "plan", "--catalog", str(cat), "--state-dir", d, "--role", "implementation"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["roles"]["implementation"]["model"], "new-coder")

    def test_unselected_new_model_warns(self):
        with tempfile.TemporaryDirectory() as d:
            def plan(rows):
                m.write_json(Path(d)/"catalog.json", {"fetched_at": time.time(), "catalog": {"data": rows}})
                result = subprocess.run([sys.executable, str(ROOT / "scripts/resolve_models.py"), "plan", "--state-dir", d], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)["warnings"]
            old = [row("old-coder"), row("frontier", "Frontier demanding complex"), row("fast", "fast affordable research everyday")]
            self.assertEqual(plan(old), [])  # first run is the baseline
            self.assertEqual(plan([row("new-coder")] + old), [])  # selected, so no warning
            warnings = plan([row("vague-new", "Our most capable model yet", isDefault=True)] + old)
            self.assertEqual(len(warnings), 1)
            self.assertIn("vague-new", warnings[0])

    def test_discovery_transport_pagination_and_failures(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d)/"server.py"
            fake.write_text('''import json,sys,time
mode=sys.argv[1]
for line in sys.stdin:
    req=json.loads(line)
    if "id" not in req: continue
    if req["method"]=="initialize":
        result={"result":{}}
    elif mode=="error":
        result={"error":{"code":-1,"message":"test"}}
    elif mode=="hang":
        time.sleep(60)
        continue
    else:
        cursor=req["params"].get("cursor")
        result={"result":{"data":[{"model":"page1" if not cursor else "page2"}],"nextCursor":"next" if (mode=="repeat" or not cursor) else None}}
    print(json.dumps({"id":req["id"],**result}),flush=True)
''')
            cmd = [sys.executable, "-u", str(fake)]
            self.assertEqual([r["model"] for r in m.discover(command=cmd+["pages"])["data"]], ["page1", "page2"])
            for mode in ("repeat", "error", "hang"):
                with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                    m.discover(timeout=0.3, command=cmd+[mode])


if __name__ == "__main__":
    unittest.main()
