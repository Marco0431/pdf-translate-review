#!/usr/bin/env python3
"""Resumable, host-executed translation workflow; no API keys or model calls.

start -> next -> execute messages in the host -> submit -> next.
The engine schedules whole-paper analysis, drafting, translation QA, targeted
repair and risk-triggered second checks. text_reviewed is NOT PDF/HTML QA.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from batch_state import atomic_write
import translation_workbench as w

VERSION = "flow-1"
TERMS = ("domain", "definition", "example")
ANALYSIS = (
    "阅读全部给定来源，建立用于翻译消歧的简洁上下文和语境术语，不生成精读报告。"
    "每条上下文事实用 evidence_ids 和 evidence_quotes 指向原文；quote 必须逐字摘自对应 source。"
    "术语给出 id/source/target/sense/unit_ids/status/variants/domain/definition/example，"
    "example 必须是适用单元中的原文片段。按词义限定 unit_ids，不将不同词义强行统一。"
    "只收录影响本篇理解的术语，不罗列普通词。难句、关键结论、OCR疑点等放入 risks，"
    "每项含 unit_id/reason/source_quote，必须有实际原文依据；没有风险则返回空数组。"
)
CONTRACT = {
    "context": [{"text": "<source-grounded fact>", "evidence_ids": ["<unit ID>"],
                 "evidence_quotes": [{"unit_id": "<same ID>", "quote": "<verbatim source excerpt>"}]}],
    "glossary": [{"id": "<term ID>", "source": "<original term>", "target": "<Chinese>",
                  "sense": "<meaning here>", "unit_ids": ["<ID>"], "status": "approved",
                  "variants": [], "domain": "<field>", "definition": "<meaning>",
                  "example": "<verbatim source excerpt>"}],
    "risks": [{"unit_id": "<ID>", "reason": "<specific concern>", "source_quote": "<verbatim excerpt>"}],
}


def write(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def envelope(stage, data, instruction):
    messages = [{"role": "system", "content": w.COMMON + instruction},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}]
    return {"stage": stage, "messages": messages, "metrics": w.message_size(messages)}


def groups_for(items, build, budget, maximum):
    groups, current = [], []
    for item in items:
        candidate = current + [item]
        if len(candidate) <= maximum and build(candidate)["metrics"]["content_utf8_bytes"] <= budget:
            current = candidate
        else:
            if current:
                groups.append(current)
            current = [item]
            w.require(build(current)["metrics"]["content_utf8_bytes"] <= budget,
                      "Full evidence exceeds request budget; enlarge budget or restructure sources, never truncate")
    if current:
        groups.append(current)
    return groups


def analysis_packet(state, ids):
    units = [x for x in state["source"]["units"] if x["id"] in ids]
    preferred = [term for term in state["personal_terms"] if any(w.term_present(x["source"], term["source"]) for x in units)]
    return envelope("analyze", {"source_units": units, "user_confirmed_term_preferences": preferred,
                                "response_contract": CONTRACT}, ANALYSIS + "用户确认术语先匹配定义与词义；词义相同时遵循其译法，不同词义不可强套。")


def initial(source, budget=24000, max_units=8, max_repairs=2, personal_terms=None):
    w.require(isinstance(source, dict) and isinstance(source.get("units"), list) and source["units"], "Source units required")
    w.require(type(budget) is int and budget > 0 and type(max_units) is int and max_units > 0, "Invalid request limits")
    w.require(type(max_repairs) is int and 0 <= max_repairs <= 5, "max_repairs must be 0..5")
    probe = {"schema_version": 1, "units": source["units"], "glossary": [],
             "context": [{"text": "Schema validation only", "evidence_ids": [source["units"][0]["id"]]}]}
    w.validate_document(probe)
    personal_terms = personal_terms or []
    w.require(isinstance(personal_terms, list), "Personal terms must be a list")
    for term in personal_terms:
        w.require(isinstance(term, dict) and term.get("confirmed_by_user") is True
                  and all(w.nonempty(term.get(k)) for k in ("source", "target", "sense", *TERMS)),
                  "Only user-confirmed terms with domain, definition and example may enter personal preferences")
    for unit in source["units"]:
        flags = unit.get("source_flags", [])
        w.require(isinstance(flags, list) and all(w.nonempty(x) for x in flags), "Invalid extraction flags")
    state = {"engine": VERSION, "phase": "analyze", "source": deepcopy(source),
             "source_sha256": w.fingerprint(source), "budget": budget, "max_units": max_units,
             "max_repairs": max_repairs, "repair_round": 0, "cursor": 0,
             "notes": [], "risks": [], "personal_terms": deepcopy(personal_terms),
             "translations": {"units": []}, "review_rows": [],
             "review_decisions": {}, "receipts": {}, "pending": None, "rejections": 0,
             "input_chars": 0, "accepted_requests": 0, "polished": False}
    ids = [x["id"] for x in source["units"]]
    state["groups"] = groups_for(ids, lambda group: analysis_packet(state, group), budget, max_units)
    return state


def validate_analysis(state, response, ids):
    w.require(isinstance(response, dict), "Analysis must be an object")
    units = [x for x in state["source"]["units"] if x["id"] in ids]
    source = {x["id"]: x["source"] for x in units}
    doc = {"schema_version": 1, "units": units, "context": response.get("context"), "glossary": response.get("glossary")}
    w.validate_document(doc)
    for fact in doc["context"]:
        quotes = fact.get("evidence_quotes", [])
        w.require(isinstance(quotes, list) and quotes, "Every context fact needs source quotes")
        for quote in quotes:
            w.require(isinstance(quote, dict) and quote.get("unit_id") in fact["evidence_ids"]
                      and w.nonempty(quote.get("quote")) and quote["quote"] in source[quote["unit_id"]],
                      "Context quote is not present in its source")
        w.require({x["unit_id"] for x in quotes} == set(fact["evidence_ids"]), "Missing quoted evidence")
    for term in doc["glossary"]:
        w.require(all(w.nonempty(term.get(key)) for key in TERMS), "Terms require domain, definition and original example")
        w.require(any(term["example"] in source[uid] for uid in term["unit_ids"]), "Term example is not in its source scope")
    risks = response.get("risks", [])
    w.require(isinstance(risks, list), "Risks must be a list")
    for risk in risks:
        w.require(isinstance(risk, dict) and risk.get("unit_id") in source and w.nonempty(risk.get("reason"))
                  and w.nonempty(risk.get("source_quote")) and risk["source_quote"] in source[risk["unit_id"]],
                  "Risk must include a real source excerpt")
    return doc, risks


def schedule(state, phase, ids=None):
    state.update(phase=phase, cursor=0)
    if phase == "synthesize":
        state["groups"] = [[]]
        return
    ids = ids or [x["id"] for x in state["document"]["units"]]
    state["groups"] = groups_for(ids, lambda group: task_packet(state, group), state["budget"], state["max_units"])


def risk_evidence(state):
    risks = list(state["risks"])
    for unit in state["document"]["units"]:
        reasons = list(unit.get("source_flags", []))
        if unit["kind"] in ("table", "algorithm", "theorem"):
            reasons.append("structured_" + unit["kind"])
        if "[[EQ:" in unit["source"]:
            reasons.append("protected_formula")
        if len(unit["source"]) > 1200:
            reasons.append("long_source_unit")
        for reason in reasons:
            risks.append({"unit_id": unit["id"], "reason": reason, "source_quote": unit["source"][:160]})
    return list({w.fingerprint(x): x for x in risks}.values())


def task_packet(state, ids):
    phase = state["phase"]
    if phase == "analyze":
        return analysis_packet(state, ids)
    if phase == "synthesize":
        return envelope(phase, {"whole_paper_notes": state["notes"], "response_contract": CONTRACT},
                        ANALYSIS + "这些笔记覆盖全文，均附原文摘录。合并为简洁的全篇上下文并统一术语；"
                        "保留不同词义、出处和真实疑点，不将可能结论改为确定结论。")
    stage = "draft" if phase == "draft" else "polish" if phase in ("repair", "polish") else "review"
    result = w.packet(state["document"], stage, state["translations"] if stage != "draft" else None, ids)
    result["stage"] = phase
    if phase == "repair":
        result["messages"][0]["content"] += "根据以下具体错误修正指定段落；未涉及的事实和语义保持不变。"
        details = {"findings": [x for x in state["review_rows"] if x["id"] in ids],
                   "automatic_issues": [x for x in state["last_qa"]["issues"] if x["unit_id"] in ids]}
        result["messages"].append({"role": "user", "content": json.dumps(details, ensure_ascii=False, separators=(",", ":"))})
    if phase in ("review", "audit"):
        result["messages"][0]["content"] += "如仅中文表达需要改善，标 needs_polish=true；若无需润色则 false。风险或错误必须写具体原译证据，不以自报置信度放行。"
        data = json.loads(result["messages"][1]["content"])
        for row in data["response_contract"]["units"]:
            row["needs_polish"] = False
        data["finding_contract"] = {"issue": "<specific mismatch>", "source_quote": "<verbatim source>",
                                    "translation_quote": "<verbatim current translation, or nearest anchor for omission>",
                                    "suggestion": "<targeted correction>"}
        result["messages"][0]["content"] += "每个未解决finding必须按finding_contract给出原译逐字摘录与修正建议；漏译用译文就近文字作为定位锚点。"
        result["messages"][1]["content"] = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if phase == "audit":
        result["messages"][0]["content"] += "这是高风险段落的第二次对照核验，不预设上一轮正确。再核对源文条件、数值、限定词及结构。"
        result["messages"].append({"role": "user", "content": json.dumps(
            {"risk_evidence": [x for x in risk_evidence(state) if x["unit_id"] in ids]}, ensure_ascii=False, separators=(",", ":"))})
    result["metrics"] = w.message_size(result["messages"])
    return result


def next_request(state):
    if state["phase"] in ("text_reviewed", "needs_review"):
        return {"status": state["phase"], "qa": state.get("last_qa"), "next": "PDF/HTML visual QA" if state["phase"] == "text_reviewed" else "Resolve recorded issues"}
    if state["pending"] is not None:
        return state["pending"]
    ids = state["groups"][state["cursor"]]
    result = task_packet(state, ids)
    if state.get("last_rejection"):
        result["messages"].append({"role": "user", "content": "上次响应未满足数据契约，请重新完成同一任务并修正：" + state["last_rejection"]})
    result["metrics"] = w.message_size(result["messages"])
    w.require(result["metrics"]["content_utf8_bytes"] <= state["budget"], "Request exceeds budget; no evidence was truncated")
    result["request_id"] = w.fingerprint({"version": VERSION, "phase": state["phase"],
                                          "cursor": state["cursor"], "round": state["repair_round"],
                                          "accepted_requests": state["accepted_requests"],
                                          "messages": result["messages"]})
    result["request_sha256"] = w.fingerprint(result["messages"])
    result["ids"] = ids
    state["pending"] = result
    return result


def full_review(state):
    by_id = {x["id"]: x for x in state["review_rows"]}
    return {"document_sha256": w.fingerprint(state["document"]),
            "translation_sha256": w.fingerprint(state["translations"]),
            "reviewer": "host-executed; see per-request receipts",
            "units": [by_id[x["id"]] for x in state["document"]["units"] if x["id"] in by_id],
            "decisions": state["review_decisions"]}


def finish_review(state):
    review = full_review(state)
    qa = w.assess(state["document"], state["translations"], review)
    state["last_qa"] = qa
    if qa["status"] != "reviewed":
        if state["repair_round"] >= state["max_repairs"]:
            state["phase"] = "needs_review"
            return
        ids = {x.split(":", 1)[0] for x in qa["blockers"]}
        affected = [x["id"] for x in state["document"]["units"] if x["id"] in ids]
        if not affected:
            state["phase"] = "needs_review"
            return
        state["repair_round"] += 1
        schedule(state, "repair", affected)
        return
    polish = [x["id"] for x in review["units"] if x.get("needs_polish")]
    if polish and not state["polished"]:
        state["polished"] = True
        schedule(state, "polish", polish)
        return
    if state["phase"] != "audit":
        risky = {x["unit_id"] for x in risk_evidence(state)}
        ids = [x["id"] for x in state["document"]["units"] if x["id"] in risky]
        if ids:
            schedule(state, "audit", ids)
            return
    state["phase"] = "text_reviewed"


def accept(state, request_id, response):
    response_hash = w.fingerprint(response)
    if request_id in state["receipts"]:
        w.require(state["receipts"][request_id]["response_sha256"] == response_hash, "Different response for an already accepted request")
        return state
    state = deepcopy(state)  # Invalid submissions cannot partially update the ledger.
    pending = state["pending"]
    w.require(pending is not None and pending["request_id"] == request_id, "No matching pending request")
    phase, ids = state["phase"], pending["ids"]
    if phase in ("analyze", "synthesize"):
        scope = ids if phase == "analyze" else [x["id"] for x in state["source"]["units"]]
        doc, risks = validate_analysis(state, response, scope)
        if phase == "analyze":
            state["notes"].append(response)
            state["risks"].extend(risks)
        else:
            state["document"] = doc
            state["risks"].extend(risks)
    elif phase in ("draft", "repair", "polish"):
        translated = w.translations_by_id(response)
        w.require(list(translated) == ids and all(w.nonempty(x) for x in translated.values()), "Response IDs/order/text do not match the request")
        existing = {x["id"]: x["text"] for x in state["translations"]["units"]}
        existing.update(translated)
        state["translations"] = {"units": [{"id": x["id"], "text": existing[x["id"]]}
                                             for x in state["document"]["units"] if x["id"] in existing]}
    else:
        w.require(isinstance(response, dict) and w.nonempty(response.get("reviewer")), "Review must identify the real executor")
        w.require(response.get("document_sha256") == w.fingerprint(state["document"])
                  and response.get("translation_sha256") == w.fingerprint(state["translations"]), "Stale review response")
        rows = response.get("units")
        w.require(isinstance(rows, list) and all(isinstance(x, dict) for x in rows)
                  and [x.get("id") for x in rows] == ids, "Review IDs do not match")
        sources = {x["id"]: x for x in state["document"]["units"]}
        translated = w.translations_by_id(state["translations"])
        for row in rows:
            w.require(row.get("verdict") in ("passed", "needs_review") and isinstance(row.get("findings"), list), "Invalid review result")
            checks = row.get("checks", [])
            w.require(isinstance(checks, list) and all(isinstance(x, str) for x in checks)
                      and set(w.required_checks(sources[row["id"]])).issubset(checks), "Incomplete review checks")
            w.require(type(row.get("needs_polish", False)) is bool, "needs_polish must be boolean")
            w.require(row["verdict"] != "passed" or row["findings"] == [], "Passed review has unresolved findings")
            w.require(row["verdict"] != "needs_review" or row["findings"], "Failed review requires concrete findings")
            for finding in row["findings"]:
                w.require(isinstance(finding, dict) and all(w.nonempty(finding.get(k)) for k in
                          ("issue", "source_quote", "translation_quote", "suggestion")), "Finding needs original/translated evidence and a correction")
                w.require(finding["source_quote"] in sources[row["id"]]["source"]
                          and finding["translation_quote"] in translated[row["id"]], "Finding quotes do not match this version of source/translation")
        decisions = response.get("decisions", {})
        w.require(isinstance(decisions, dict) and all(w.nonempty(v) for v in decisions.values()), "Invalid candidate decisions")
        state["review_rows"] = [x for x in state["review_rows"] if x["id"] not in ids] + rows
        state["review_decisions"].update(decisions)
    state["receipts"][request_id] = {"stage": phase, "ids": ids, "response_sha256": response_hash,
                                    "reviewer": response.get("reviewer"), "response": response}
    state["accepted_requests"] += 1
    state["input_chars"] += pending["metrics"]["content_chars"]
    state["cursor"] += 1
    state["pending"] = None
    state["rejections"] = 0
    state.pop("last_rejection", None)
    if state["cursor"] == len(state["groups"]):
        if phase == "analyze":
            if len(state["notes"]) == 1:
                # One analyzed batch already covers the whole source; no extra
                # synthesis call can add missing cross-batch context here.
                state["document"] = doc
                schedule(state, "draft")
            else:
                schedule(state, "synthesize")
        elif phase == "synthesize":
            schedule(state, "draft")
        elif phase in ("draft", "repair", "polish"):
            state["review_rows"], state["review_decisions"] = [], {}
            schedule(state, "review")
        else:
            finish_review(state)
    return state


def load(path):
    wrapper = w.read(path)
    w.require(isinstance(wrapper, dict) and isinstance(wrapper.get("state"), dict), "Invalid flow state")
    state = wrapper["state"]
    w.require(wrapper.get("sha256") == w.fingerprint(state), "Flow state checksum mismatch")
    w.require(state.get("engine") == VERSION and state["source_sha256"] == w.fingerprint(state["source"]), "Changed source or engine version")
    for origin in state.get("input_origins", []):
        w.require(w.fingerprint(w.read(origin["path"])) == origin["sha256"], "Input file changed; start a new flow, do not reuse old QA")
    return state


def save(path, state):
    write(path, {"sha256": w.fingerprint(state), "state": state})


def export(state, out):
    w.require(state["phase"] == "text_reviewed", "Export requires completed translation QA")
    out = Path(out)
    outputs = [out / name for name in ("document.json", "translations.json", "translation-review.json", "text-qa.json", "translation.protected.md")]
    protected = {Path(x["path"]).resolve() for x in state.get("input_origins", [])}
    w.require(not any(x.resolve() in protected for x in outputs), "Export cannot overwrite original inputs")
    write(out / "document.json", state["document"])
    write(out / "translations.json", state["translations"])
    write(out / "translation-review.json", full_review(state))
    write(out / "text-qa.json", state["last_qa"])
    protected = "\n\n".join(x["text"] for x in state["translations"]["units"])
    atomic_write(out / "translation.protected.md", (protected + "\n").encode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--source", required=True)
    start.add_argument("--glossary", help="Optional JSON list of user-confirmed contextual term preferences")
    start.add_argument("--max-input-bytes", type=int, default=24000)
    start.add_argument("--max-units", type=int, default=8)
    start.add_argument("--max-repairs", type=int, default=2)
    upcoming = sub.add_parser("next")
    upcoming.add_argument("--out", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--request-id", required=True)
    submit.add_argument("--response", required=True)
    status = sub.add_parser("status")
    exporting = sub.add_parser("export")
    exporting.add_argument("--out-dir", required=True)
    for cmd in (start, upcoming, submit, status, exporting):
        cmd.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            w.require(not Path(args.state).exists(), "State already exists; use next to resume")
            w.require(Path(args.state).resolve() != Path(args.source).resolve(), "State cannot overwrite source")
            state = initial(w.read(args.source), args.max_input_bytes, args.max_units, args.max_repairs,
                            w.read(args.glossary) if args.glossary else None)
            state["input_origins"] = [{"path": str(Path(p).resolve()), "sha256": w.fingerprint(w.read(p))}
                                      for p in (args.source, args.glossary) if p]
            save(args.state, state)
        else:
            state = load(args.state)
            if args.command == "next":
                w.require(Path(args.state).resolve() != Path(args.out).resolve(), "Output cannot overwrite state")
                request = next_request(state)
                save(args.state, state)
                write(args.out, request)
            elif args.command == "submit":
                try:
                    response = w.read(args.response)
                    state = accept(state, args.request_id, response)
                except ValueError as error:
                    if state["pending"] and state["pending"]["request_id"] == args.request_id:
                        state["rejections"] += 1
                        state["last_rejection"] = str(error)
                        state["pending"] = None
                        if state["rejections"] >= 2:
                            state["phase"] = "needs_review"
                            state["last_qa"] = {"status": "needs_review", "blockers": ["repeated_invalid_response"], "detail": str(error)}
                        save(args.state, state)
                    raise
                save(args.state, state)
            elif args.command == "export":
                w.require(Path(args.state).resolve().parent != Path(args.out_dir).resolve(), "Use a separate export directory")
                export(state, args.out_dir)
        print(json.dumps({"phase": state["phase"], "accepted_requests": state["accepted_requests"],
                          "repair_round": state["repair_round"], "quality_scope": "translation_text_only"}, ensure_ascii=False))
        return 2 if state["phase"] == "needs_review" else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
