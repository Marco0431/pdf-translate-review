from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import translation_workbench as workbench


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.doc = workbench.read(ROOT / "tests/fixtures/translation-case.json")
        self.translations = workbench.read(ROOT / "tests/fixtures/translation-good.json")

    def review(self):
        # Simulated completed review for testing the protocol, not an LLM evaluation.
        return {"document_sha256": workbench.fingerprint(self.doc),
                "translation_sha256": workbench.fingerprint(self.translations),
                "reviewer": "synthetic-test-reviewer",
                "units": [{"id": row["id"], "verdict": "passed", "checks": workbench.required_checks(row),
                           "findings": []} for row in self.doc["units"]], "decisions": {}}

    def test_good_alignment_still_requires_semantic_review(self):
        self.assertEqual(workbench.inspect(self.doc, self.translations), [])
        self.assertIn("semantic_review_missing", workbench.assess(self.doc, self.translations)["blockers"])
        self.assertEqual(workbench.assess(self.doc, self.translations, self.review())["status"], "reviewed")

    def test_missing_and_reordered_units_block_delivery(self):
        self.translations["units"].reverse()
        self.assertIn("document:alignment", workbench.assess(self.doc, self.translations, self.review())["blockers"])
        self.translations["units"].pop()
        self.assertTrue(any(x["code"] == "empty_translation" for x in workbench.inspect(self.doc, self.translations)))

    def test_protected_token_swap_is_not_waivable(self):
        self.translations["units"][2]["text"] = self.translations["units"][2]["text"].replace("fig1", "fig2")
        review = self.review()
        review["decisions"]["p1-fig1:protected_tokens"] = "Accepting this must not bypass a hard error"
        self.assertIn("p1-fig1:protected_tokens", workbench.assess(self.doc, self.translations, review)["blockers"])

    def test_numeric_change_needs_explicit_source_grounded_review(self):
        self.translations["units"][0]["text"] = self.translations["units"][0]["text"].replace("12%", "百分之十二")
        review = self.review()
        self.assertIn("p1-b1:numbers", workbench.assess(self.doc, self.translations, review)["blockers"])
        review["decisions"]["p1-b1:numbers"] = "原文 12% 对应中文百分之十二，数值相同。"
        self.assertEqual(workbench.assess(self.doc, self.translations, review)["status"], "reviewed")

    def test_term_scope_preserves_two_senses(self):
        self.assertEqual(workbench.inspect(self.doc, self.translations), [])
        self.translations["units"][-1]["text"] = "实验室安全策略要求每次实验都有人监督。"
        issues = workbench.inspect(self.doc, self.translations)
        self.assertEqual([x["code"] for x in issues], ["term-safety-policy"])

    def test_overlapping_term_senses_rejected(self):
        self.doc["glossary"][1]["unit_ids"] = ["p1-b1"]
        with self.assertRaises(ValueError):
            workbench.validate_document(self.doc)

    def test_polish_or_context_change_invalidates_review(self):
        review = self.review()
        self.translations["units"][1]["text"] += "因此效果确定。"
        self.assertIn("stale_review", workbench.assess(self.doc, self.translations, review)["blockers"])
        review = self.review()
        self.doc["context"][0]["text"] = "Changed context"
        self.assertIn("stale_review", workbench.assess(self.doc, self.translations, review)["blockers"])

    def test_unresolved_semantic_error_blocks_even_if_regex_passes(self):
        self.translations["units"][1]["text"] = "这证明该方法能够改善真实机器人上的表现。"
        self.assertEqual(workbench.inspect(self.doc, self.translations), [])
        review = self.review()
        review["units"][1].update(verdict="needs_review", findings=["原文 does not establish 被反向翻译。"])
        self.assertIn("p1-b2:semantic_review", workbench.assess(self.doc, self.translations, review)["blockers"])

    def test_incomplete_review_and_missing_kind_specific_checks(self):
        review = self.review()
        review["units"][2]["checks"].remove("panel_mapping")
        self.assertIn("p1-fig1:semantic_review", workbench.assess(self.doc, self.translations, review)["blockers"])
        review["units"].pop()
        self.assertIn("review_coverage", workbench.assess(self.doc, self.translations, review)["blockers"])

    def test_context_requires_real_source_ids(self):
        self.doc["context"][0]["evidence_ids"] = ["nonexistent"]
        with self.assertRaises(ValueError):
            workbench.validate_document(self.doc)

    def test_packet_has_scoped_terms_and_read_only_context(self):
        result = workbench.packet(self.doc, "draft", selected=["p2-b1"])
        data = json.loads(result["messages"][1]["content"])
        self.assertEqual([x["id"] for x in data["glossary"]], ["safety-policy"])
        self.assertEqual([x["id"] for x in data["selected_units"]], ["p2-b1"])
        self.assertIn("p1-b1", [x["id"] for x in data["read_only_context_units"]])
        self.assertEqual([x["id"] for x in data["response_contract"]["units"]], ["p2-b1"])

    def test_real_cli_packet_check_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            document, translation, review = [root / name for name in ("doc.json", "translation.json", "review.json")]
            for path, value in ((document, self.doc), (translation, self.translations), (review, self.review())):
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            base = [sys.executable, str(ROOT / "scripts/translation_workbench.py")]
            args = ["--document", str(document), "--translations", str(translation)]
            packet = subprocess.run(base + ["packet", "--stage", "review", *args, "--out", str(root / "packet.json")], capture_output=True)
            self.assertEqual(packet.returncode, 0, packet.stderr)
            missing = subprocess.run(base + ["check", *args, "--out", str(root / "qa.json")], capture_output=True)
            self.assertEqual(missing.returncode, 2, missing.stderr)
            passed = subprocess.run(base + ["check", *args, "--review", str(review), "--out", str(root / "qa.json")], capture_output=True)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertEqual(workbench.read(root / "qa.json")["status"], "reviewed")
            overwrite = subprocess.run(base + ["check", *args, "--out", str(document)], capture_output=True)
            self.assertEqual(overwrite.returncode, 1)

    def test_compact_packet_is_lossless_and_smaller(self):
        compact = workbench.packet(self.doc, "review", self.translations)
        pretty = workbench.packet(self.doc, "review", self.translations, pretty=True)
        self.assertEqual(compact["messages"][0], pretty["messages"][0])
        self.assertEqual(json.loads(compact["messages"][1]["content"]),
                         json.loads(pretty["messages"][1]["content"]))
        self.assertLess(compact["metrics"]["content_utf8_bytes"], pretty["metrics"]["content_utf8_bytes"])
        data = json.loads(compact["messages"][1]["content"])
        for source, contract in zip(self.doc["units"], data["response_contract"]["units"]):
            self.assertEqual(contract["checks"], workbench.required_checks(source))

    def test_plan_preserves_all_source_units_context_and_evidence(self):
        result = workbench.plan(self.doc, "review", self.translations, max_input_bytes=20000, max_units=2)
        self.assertEqual([uid for item in result["packets"] for uid in item["ids"]],
                         [unit["id"] for unit in self.doc["units"]])
        for item in result["packets"]:
            self.assertLessEqual(item["metrics"]["content_utf8_bytes"], 20000)
            data = json.loads(item["messages"][1]["content"])
            self.assertEqual(data["context"], self.doc["context"])
            visible = {x["id"]: x for x in data["selected_units"] + data["read_only_context_units"]}
            for fact in self.doc["context"]:
                for uid in fact["evidence_ids"]:
                    self.assertIn(uid, visible)
            for original in self.doc["units"]:
                if original["id"] in visible:
                    self.assertEqual(visible[original["id"]], original)

    def test_plan_reduces_repeated_payload_without_skipping_units(self):
        singles = [workbench.packet(self.doc, "draft", selected=[row["id"]]) for row in self.doc["units"]]
        planned = workbench.plan(self.doc, "draft", max_input_bytes=20000)
        self.assertLess(planned["metrics"]["requests"], len(singles))
        self.assertLess(planned["metrics"]["total_content_utf8_bytes"],
                        sum(row["metrics"]["content_utf8_bytes"] for row in singles))

    def test_oversized_context_is_rejected_not_truncated(self):
        self.doc["context"][0]["text"] = "证据不能截断" * 1000
        with self.assertRaisesRegex(ValueError, "exceeds"):
            workbench.plan(self.doc, "draft", max_input_bytes=1000)

    def test_request_hash_binds_exact_messages(self):
        first = workbench.packet(self.doc, "draft")
        again = workbench.packet(self.doc, "draft")
        self.assertEqual(first["request_sha256"], again["request_sha256"])
        self.doc["units"][0]["source"] += " Extra condition."
        changed = workbench.packet(self.doc, "draft")
        self.assertNotEqual(first["request_sha256"], changed["request_sha256"])


if __name__ == "__main__":
    unittest.main()
