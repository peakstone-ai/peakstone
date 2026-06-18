"""Extract code files from a model's chat response.

Supports two styles:
  1. Single solution: take the last fenced code block (optionally filtered by language)
     and write it to the challenge's declared solution_file.
  2. Multi-file: fenced blocks tagged with a path, via either
        ```ts file=src/foo.ts        (info-string attribute)
     or a comment on the first line of the block:
        // file: src/foo.ts
        # file: src/foo.py
     Any block carrying a path is written to that path; untagged blocks fall back to
     solution_file (last one wins).
"""
from __future__ import annotations

import re

_FENCE = re.compile(
    r"```([^\n`]*)\n(.*?)```",
    re.DOTALL,
)
_PATH_IN_INFO = re.compile(r"(?:file|path|title)\s*[=:]\s*([^\s`]+)")
_PATH_IN_COMMENT = re.compile(r"^\s*(?://|#)\s*(?:file|path)\s*:\s*(\S+)\s*$")

# rough language -> fence-tag aliases for filtering single-file extraction
_LANG_TAGS = {
    "python": {"python", "py"},
    "javascript": {"javascript", "js", "node"},
    "typescript": {"typescript", "ts"},
    "go": {"go", "golang"},
    "rust": {"rust", "rs"},
}


def extract_files(text: str, default_filename: str, language: str) -> dict[str, str]:
    """Return {relative_path: content}. Empty dict if no code found."""
    blocks: list[tuple[str, str]] = _FENCE.findall(text or "")
    if not blocks:
        return {}

    tags = _LANG_TAGS.get(language, set())
    out: dict[str, str] = {}
    untagged_default: str | None = None

    for info, body in blocks:
        info = info.strip()
        path = None
        m = _PATH_IN_INFO.search(info)
        if m:
            path = m.group(1)
        else:
            first_line = body.split("\n", 1)[0]
            cm = _PATH_IN_COMMENT.match(first_line)
            if cm:
                path = cm.group(1)
                body = body.split("\n", 1)[1] if "\n" in body else ""

        if path:
            out[path] = body
            continue

        # untagged block: candidate for the single default file.
        tag_word = info.split()[0].lower() if info else ""
        if not tags or tag_word in tags or tag_word == "":
            untagged_default = body  # last matching wins

    if untagged_default is not None:
        out.setdefault(default_filename, untagged_default)
    elif default_filename not in out and blocks:
        # nothing matched language filter; fall back to the last block of any kind
        out[default_filename] = blocks[-1][1]

    return out
