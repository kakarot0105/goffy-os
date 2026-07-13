from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [ROOT / "hub", ROOT / "protocol", ROOT / "android"]
SKIP_PARTS = {".git", ".venv", ".gradle", "build", "__pycache__"}

PROHIBITED_SOURCE_PATTERNS = {
    "subprocess API": re.compile(r"\bsubprocess\b"),
    "os.system": re.compile(r"\bos\.system\s*\("),
    "shell execution": re.compile(r"shell\s*=\s*True"),
    "dynamic eval": re.compile(r"\beval\s*\("),
    "dynamic exec": re.compile(r"\bexec\s*\("),
}

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}

TEXT_SUFFIXES = {
    ".json",
    ".kts",
    ".kt",
    ".md",
    ".properties",
    ".py",
    ".toml",
    ".xml",
    ".yml",
    ".yaml",
}


def candidate_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIP_PARTS.intersection(path.parts)
    )


def main() -> int:
    findings: list[str] = []
    source_files = {
        path
        for source_root in SOURCE_ROOTS
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".kt", ".kts"}
    }

    for path in candidate_files():
        text = path.read_text(encoding="utf-8")
        patterns = dict(SECRET_PATTERNS)
        if path in source_files:
            patterns.update(PROHIBITED_SOURCE_PATTERNS)
        for label, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {label}")

    if findings:
        print("Security scan failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print(f"Security scan passed ({len(candidate_files())} text files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
