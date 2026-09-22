import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "batch_state", Path(__file__).resolve().parents[1] / "scripts" / "batch_state.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "论文.pdf"
        self.pdf.write_bytes(b"%PDF-test-fixture")
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps({key: "test" for key in cache.PROFILE_KEYS}), encoding="utf-8")
        self.state = self.root / "work" / "cache.json"
        self.source = self.root / "source.txt"
        self.source.write_text("See [[IMG:fig-1]] and [[EQ:eq-1]].", encoding="utf-8")
        self.translated = self.root / "translated.txt"
        self.translated.write_text("参见 [[IMG:fig-1]] 与 [[EQ:eq-1]]。", encoding="utf-8")
        self.out = self.root / "reused.txt"
        cache.initialize(self.state, self.pdf, self.profile)

    def put(self, validated=True):
        return cache.put(self.state, "p001-b001", self.source, self.translated, validated)

    def test_round_trip_and_idempotent_init(self):
        self.put()
        cache.initialize(self.state, self.pdf, self.profile)
        self.assertTrue(cache.get(self.state, "p001-b001", self.source, self.out))
        self.assertEqual(self.out.read_bytes(), self.translated.read_bytes())

    def test_changed_profile_and_pdf_rejected(self):
        for target in (self.profile, self.pdf):
            with self.subTest(target=target):
                before = target.read_bytes()
                target.write_bytes(before + b" ")
                with self.assertRaises(ValueError):
                    cache.load(self.state)
                target.write_bytes(before)

    def test_changed_block_misses_without_overwriting_output(self):
        self.put()
        self.source.write_text("Changed", encoding="utf-8")
        self.out.write_text("keep", encoding="utf-8")
        self.assertFalse(cache.get(self.state, "p001-b001", self.source, self.out))
        self.assertEqual(self.out.read_text(), "keep")

    def test_draft_is_saved_but_not_reused(self):
        self.put(False)
        self.assertFalse(cache.get(self.state, "p001-b001", self.source, self.out))

    def test_token_identity_and_multiplicity(self):
        for output in ("[[IMG:fig-2]] [[EQ:eq-1]]", "[[IMG:fig-1]] [[EQ:eq-1]] [[EQ:eq-1]]", ""):
            with self.subTest(output=output):
                self.translated.write_text(output, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.put()
                self.assertEqual(cache.load(self.state)["blocks"], {})

    def test_tampered_cache_rejected(self):
        self.put()
        state = cache.load(self.state)
        state["blocks"]["p001-b001"]["translation"] += "tampered"
        cache.save(self.state, state)
        with self.assertRaises(ValueError):
            cache.get(self.state, "p001-b001", self.source, self.out)

    def test_output_cannot_destroy_inputs(self):
        self.put()
        for target in (self.state, self.source, self.pdf, self.profile):
            with self.subTest(target=target):
                before = target.read_bytes()
                with self.assertRaises(ValueError):
                    cache.get(self.state, "p001-b001", self.source, target)
                self.assertEqual(target.read_bytes(), before)

    def test_cli_exit_codes(self):
        self.assertEqual(cache.main(["get", "--state", str(self.state), "--id", "missing",
                                    "--source", str(self.source), "--out", str(self.out)]), 2)
        self.assertEqual(cache.main(["summary", "--state", str(self.state)]), 0)

    def test_context_dependency_changes_invalidate_cache(self):
        context = self.root / "context.json"
        context.write_text('{"fact":"original"}', encoding="utf-8")
        profile = json.loads(self.profile.read_text())
        profile["inputs"] = {"context": "context.json"}
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        state = self.root / "context-cache.json"
        cache.initialize(state, self.pdf, self.profile)
        cache.put(state, "p001-b001", self.source, self.translated, True)
        with self.assertRaises(ValueError):
            cache.get(state, "p001-b001", self.source, context)
        context.write_text('{"fact":"changed"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            cache.get(state, "p001-b001", self.source, self.out)

    def test_invalid_dependency_configuration_rejected(self):
        profile = json.loads(self.profile.read_text())
        profile["inputs"] = ["context.json"]
        self.profile.write_text(json.dumps(profile), encoding="utf-8")
        with self.assertRaises(ValueError):
            cache.initialize(self.root / "new-cache.json", self.pdf, self.profile)


if __name__ == "__main__":
    unittest.main()
