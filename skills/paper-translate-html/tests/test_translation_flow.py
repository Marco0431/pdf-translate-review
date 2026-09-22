from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import translation_flow as flow
import translation_workbench as w


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.source = w.read(ROOT / "tests/fixtures/translation-case.json")
        self.good = w.read(ROOT / "tests/fixtures/translation-good.json")

    def analysis(self, ids=None):
        units = [x for x in self.source["units"] if ids is None or x["id"] in ids]
        uid, text = units[0]["id"], units[0]["source"]
        return {"context": [{"text": "合成测试材料的局部事实，需结合原文。", "evidence_ids": [uid],
                             "evidence_quotes": [{"unit_id": uid, "quote": text}]}],
                "glossary": [], "risks": []}

    def response(self, state):
        phase = state["phase"]
        request = flow.next_request(state)
        if phase in ("analyze", "synthesize"):
            return self.analysis(request["ids"] if phase == "analyze" else None)
        if phase in ("draft", "repair", "polish"):
            return {"units": [deepcopy(x) for x in self.good["units"] if x["id"] in request["ids"]]}
        data = json.loads(request["messages"][1]["content"])
        review = deepcopy(data["response_contract"])
        review["reviewer"] = "test-double; not a real translation-quality evaluation"
        review["decisions"] = {}
        for row in review["units"]:
            row.update(verdict="passed", findings=[], needs_polish=False)
        return review

    def step(self, state, response=None):
        request = flow.next_request(state)
        return flow.accept(state, request["request_id"], response if response is not None else self.response(state))

    def reach(self, state, phase):
        for _ in range(40):
            if state["phase"] == phase:
                return state
            state = self.step(state)
        self.fail("Flow did not reach " + phase)

    def test_full_flow_requires_analysis_review_and_risk_audit(self):
        state = flow.initial(self.source)
        state = self.reach(state, "audit")
        self.assertIn("p2-table1", flow.next_request(state)["ids"])
        state = self.reach(state, "text_reviewed")
        stages = [x["stage"] for x in state["receipts"].values()]
        self.assertEqual(stages, ["analyze", "draft", "review", "audit"])
        self.assertEqual(state["translations"], self.good)
        self.assertEqual(state["last_qa"]["status"], "reviewed")

    def test_all_source_batches_analyzed_before_any_draft(self):
        state = flow.initial(self.source, max_units=2)
        analyzed = []
        while state["phase"] == "analyze":
            analyzed.extend(flow.next_request(state)["ids"])
            state = self.step(state)
        self.assertEqual(analyzed, [x["id"] for x in self.source["units"]])
        self.assertEqual(state["phase"], "synthesize")
        self.assertEqual(state["translations"]["units"], [])

    def test_fabricated_context_or_glossary_evidence_rejected(self):
        state = flow.initial(self.source)
        request = flow.next_request(state)
        response = self.analysis()
        response["context"][0]["evidence_quotes"][0]["quote"] = "NOT IN ORIGINAL"
        before = deepcopy(state)
        with self.assertRaises(ValueError):
            flow.accept(state, request["request_id"], response)
        self.assertEqual(before, state)
        response = self.analysis()
        response["glossary"] = [dict(self.source["glossary"][0], domain="robotics", definition="control rule", example="NOT IN ORIGINAL")]
        with self.assertRaises(ValueError):
            flow.accept(state, request["request_id"], response)

    def test_risk_requires_quote_and_extraction_flags_trigger_audit(self):
        state = flow.initial(self.source)
        bad = self.analysis()
        bad["risks"] = [{"unit_id": "p1-b1", "reason": "scan", "source_quote": "invented"}]
        with self.assertRaises(ValueError):
            self.step(state, bad)
        self.source["units"][0]["source_flags"] = ["ocr_uncertainty"]
        state = self.reach(flow.initial(self.source), "audit")
        self.assertIn("p1-b1", flow.next_request(state)["ids"])

    def test_targeted_repair_followed_by_full_final_review(self):
        state = self.reach(flow.initial(self.source), "draft")
        wrong = deepcopy(self.good)
        wrong["units"][1]["text"] = "这证明该方法改善真实机器人表现。"
        state = self.step(state, wrong)
        review = self.response(state)
        review["units"][1].update(verdict="needs_review", findings=[{
            "issue": "原文 does not establish 被译反。", "source_quote": "does not establish",
            "translation_quote": "这证明", "suggestion": "保留否定，应译为这并不能证明。"}])
        state = self.step(state, review)
        self.assertEqual(state["phase"], "repair")
        self.assertEqual(flow.next_request(state)["ids"], ["p1-b2"])
        state = self.step(state)
        self.assertEqual(state["phase"], "review")
        self.assertEqual(flow.next_request(state)["ids"], [x["id"] for x in self.source["units"]])
        self.assertEqual(self.reach(state, "text_reviewed")["translations"], self.good)

    def test_polish_without_changes_does_not_reuse_request_id_or_loop(self):
        state = self.reach(flow.initial(self.source), "review")
        first_request = flow.next_request(state)["request_id"]
        response = self.response(state)
        response["units"][0]["needs_polish"] = True
        state = self.step(state, response)
        self.assertEqual(state["phase"], "polish")
        state = self.step(state)
        self.assertEqual(state["phase"], "review")
        self.assertNotEqual(flow.next_request(state)["request_id"], first_request)
        self.reach(state, "text_reviewed")

    def test_repair_limit_stops_without_false_success(self):
        state = self.reach(flow.initial(self.source, max_repairs=0), "review")
        response = self.response(state)
        response["units"][0].update(verdict="needs_review", findings=[{
            "issue": "Test-injected unresolved condition", "source_quote": "provided that",
            "translation_quote": "条件下", "suggestion": "Recheck the condition against source evidence."}])
        state = self.step(state, response)
        self.assertEqual(state["phase"], "needs_review")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                flow.export(state, temp)

    def test_resume_idempotency_and_tamper_detection(self):
        state = flow.initial(self.source)
        request = flow.next_request(state)
        response = self.response(state)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "flow.json"
            flow.save(path, state)
            restored = flow.load(path)
            self.assertEqual(flow.next_request(restored), request)
            done = flow.accept(restored, request["request_id"], response)
            self.assertEqual(flow.accept(done, request["request_id"], response), done)
            changed = deepcopy(response)
            changed["context"][0]["text"] = "Different response"
            with self.assertRaises(ValueError):
                flow.accept(done, request["request_id"], changed)
            wrapper = w.read(path)
            wrapper["state"]["source"]["units"][0]["source"] += "changed"
            flow.write(path, wrapper)
            with self.assertRaises(ValueError):
                flow.load(path)

    def test_type_specific_instructions_are_in_real_requests(self):
        state = self.reach(flow.initial(self.source), "draft")
        data = json.loads(flow.next_request(state)["messages"][1]["content"])
        self.assertIn("table", data["content_type_instructions"])
        self.assertIn("caption", data["content_type_instructions"])

    def test_personal_glossary_only_accepts_confirmed_scoped_preferences(self):
        term = dict(self.source["glossary"][0], domain="robotics", definition="control rule",
                    example=self.source["units"][0]["source"], confirmed_by_user=True)
        state = flow.initial(self.source, personal_terms=[term])
        data = json.loads(flow.next_request(state)["messages"][1]["content"])
        self.assertEqual(data["user_confirmed_term_preferences"][0]["target"], "策略")
        term["confirmed_by_user"] = False
        with self.assertRaises(ValueError):
            flow.initial(self.source, personal_terms=[term])

    def test_two_malformed_submissions_stop_and_remain_inspectable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, response = root / "state.json", root / "response.json"
            flow.save(path, flow.initial(self.source))
            flow.write(response, {})
            for _ in range(2):
                state = flow.load(path)
                request = flow.next_request(state)
                flow.save(path, state)
                code = flow.main(["submit", "--state", str(path), "--request-id", request["request_id"], "--response", str(response)])
                self.assertEqual(code, 1)
            self.assertEqual(flow.load(path)["phase"], "needs_review")

    def test_oversize_fails_without_silent_truncation(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            flow.initial(self.source, budget=10)

    def test_findings_must_quote_current_original_and_translation(self):
        state = self.reach(flow.initial(self.source), "review")
        response = self.response(state)
        response["units"][0].update(verdict="needs_review", findings=[{
            "issue": "Supposed omission", "source_quote": "made-up source quote",
            "translation_quote": "条件下", "suggestion": "Correct the translation"}])
        with self.assertRaisesRegex(ValueError, "quotes"):
            self.step(state, response)

    def test_cli_source_change_prevents_stale_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, state = root / "source.json", root / "state.json"
            flow.write(source, self.source)
            self.assertEqual(flow.main(["start", "--source", str(source), "--state", str(state)]), 0)
            changed = deepcopy(self.source)
            changed["units"][0]["source"] += " Changed."
            flow.write(source, changed)
            with self.assertRaisesRegex(ValueError, "Input file changed"):
                flow.load(state)

    def test_export_cannot_overwrite_source_document(self):
        state = self.reach(flow.initial(self.source), "text_reviewed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "document.json"
            flow.write(source, self.source)
            state["input_origins"] = [{"path": str(source), "sha256": w.fingerprint(self.source)}]
            before = source.read_bytes()
            with self.assertRaisesRegex(ValueError, "overwrite"):
                flow.export(state, root)
            self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
