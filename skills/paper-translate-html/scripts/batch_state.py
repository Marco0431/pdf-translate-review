#!/usr/bin/env python3
"""Local, single-writer translation block cache. No model or Zotero calls.

Exit codes: 0 success, 1 invalid input/state, 2 cache miss.
--validated records the caller's review; it does not certify translation quality.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

TOKENS = re.compile(r"\[\[(?:EQ|IMG|CITE):[^\]\r\n]+\]\]")
PROFILE_KEYS = {
    "model", "target_language", "prompt_version", "glossary_sha256",
    "extractor_version", "formula_mode",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cache-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(path, state):
    atomic_write(path, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load(path):
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("Unsupported or invalid cache schema")
    if not isinstance(state.get("blocks"), dict):
        raise ValueError("Invalid block index")
    records = {key: state[key] for key in ("pdf", "profile")}
    records.update(state.get("dependencies", {}))
    for key, record in records.items():
        if file_digest(record["path"]) != record["sha256"]:
            raise ValueError(f"{key} changed; create a new cache for the new input")
    return state


def initialize(path, pdf, profile):
    pdf, profile = Path(pdf).resolve(), Path(profile).resolve()
    path = Path(path).resolve()
    if path in (pdf, profile):
        raise ValueError("State must not overwrite an input")
    config = json.loads(profile.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not PROFILE_KEYS.issubset(config):
        raise ValueError("Profile requires: " + ", ".join(sorted(PROFILE_KEYS)))
    if any(not isinstance(config[key], str) or not config[key].strip() for key in PROFILE_KEYS):
        raise ValueError("Required profile values must be nonempty strings")
    records = {key: {"path": str(value), "sha256": file_digest(value)}
               for key, value in (("pdf", pdf), ("profile", profile))}
    dependencies = {}
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("Profile inputs must map names to file paths")
    for name, relative in inputs.items():
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("Dependency path must be a nonempty string")
        if name in records:
            raise ValueError("Dependency name conflicts with a built-in input")
        target = (profile.parent / relative).resolve()
        if target == path:
            raise ValueError("Dependency must not be the cache file")
        dependencies[name] = {"path": str(target), "sha256": file_digest(target)}
    if path.exists():
        current = load(path)
        if any(current[key] != records[key] for key in records):
            raise ValueError("Cache belongs to different inputs; use another state path")
        if current.get("dependencies", {}) != dependencies:
            raise ValueError("Cache dependencies changed; use another state path")
        return current
    state = {"schema_version": 1, **records, "dependencies": dependencies, "blocks": {}}
    save(path, state)
    return state


def put(path, block_id, source, translation, validated=False):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", block_id):
        raise ValueError("Invalid block ID")
    state = load(path)
    if Path(path).resolve() in (Path(source).resolve(), Path(translation).resolve()):
        raise ValueError("Block inputs must not be the cache file")
    src = Path(source).read_bytes()
    raw = Path(translation).read_bytes()
    source_text, translated = src.decode("utf-8-sig"), raw.decode("utf-8-sig")
    if not source_text.strip():
        raise ValueError("Source block is empty")
    issues = []
    if not translated.strip():
        issues.append("empty_translation")
    if Counter(TOKENS.findall(source_text)) != Counter(TOKENS.findall(translated)):
        issues.append("protected_tokens_changed")
    if validated and issues:
        raise ValueError("Cannot validate block: " + ", ".join(issues))
    # Keep the source digest and UTF-8 output together in the atomic manifest.
    # No orphaned files or partially updated pairs after interruption.
    state["blocks"][block_id] = {
        "source_sha256": digest(src),
        "translation": translated,
        "translation_sha256": digest(translated.encode("utf-8")),
        "status": "validated" if validated else "needs_review",
        "issues": issues,
    }
    save(path, state)
    return state["blocks"][block_id]


def get(path, block_id, source, out):
    state = load(path)
    record = state["blocks"].get(block_id)
    if not record or record["status"] != "validated":
        return False
    if file_digest(source) != record["source_sha256"]:
        return False
    data = record["translation"].encode("utf-8")
    if digest(data) != record["translation_sha256"]:
        raise ValueError("Cached translation checksum mismatch")
    protected = [path, source, state["pdf"]["path"], state["profile"]["path"]]
    protected.extend(row["path"] for row in state.get("dependencies", {}).values())
    if Path(out).resolve() in [Path(item).resolve() for item in protected]:
        raise ValueError("Output must not overwrite cache or source inputs")
    atomic_write(out, data)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize or verify an existing cache")
    init.add_argument("--pdf", required=True)
    init.add_argument("--profile", required=True)
    put_parser = commands.add_parser("put", help="Store one reviewed or draft block")
    put_parser.add_argument("--translation", required=True)
    put_parser.add_argument("--validated", action="store_true")
    get_parser = commands.add_parser("get", help="Reuse a validated matching block")
    get_parser.add_argument("--out", required=True)
    for item in (put_parser, get_parser):
        item.add_argument("--id", required=True)
        item.add_argument("--source", required=True)
    summary = commands.add_parser("summary", help="Report stored blocks, not whole-paper readiness")
    for item in (init, put_parser, get_parser, summary):
        item.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            initialize(args.state, args.pdf, args.profile)
            result = {"cache": "initialized"}
        elif args.command == "put":
            record = put(args.state, args.id, args.source, args.translation, args.validated)
            result = {"id": args.id, "status": record["status"], "issues": record["issues"]}
        elif args.command == "get":
            if not get(args.state, args.id, args.source, args.out):
                print(json.dumps({"cache": "miss", "id": args.id}))
                return 2
            result = {"cache": "hit", "id": args.id}
        else:
            state = load(args.state)
            counts = Counter(row["status"] for row in state["blocks"].values())
            result = {"stored_blocks": len(state["blocks"]), "counts": dict(counts),
                      "paper_readiness": "not_evaluated"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
