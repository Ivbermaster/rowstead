"""Bounded publication preflight. Never read private/runtime directories or print values.

Run `python scripts/check_release.py --require-git` after staging an explicit file list.
The source allowlist below is deliberate: review it when adding a new public asset.
This is a local heuristic guard, not a complete secret detector or a history audit.
"""

import argparse
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "alembic.ini",
    "compose.yaml",
    "CONTRIBUTING.md",
    "Dockerfile",
    "LICENSE",
    "pyproject.toml",
    "README.md",
    "requirements.lock",
    "SECURITY.md",
}
SOURCE_DIRS = {"app", "demo", "docs", "examples", "migrations", "scripts", "tests", ".github"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".ini",
    ".yaml",
    ".yml",
    ".js",
    ".css",
    ".html",
    ".csv",
    ".txt",
    ".json",
    ".lock",
    ".mako",
}
PUBLIC_IMAGES = {
    "docs/screenshots/dashboard.png",
    "docs/screenshots/import.png",
    "docs/screenshots/task.png",
    "docs/screenshots/task-mobile.png",
}
PRIVATE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "data",
    "artifacts",
    "outputs",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".secrets",
    "secrets",
    "backups",
}
PRIVATE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".dump",
    ".backup",
    ".sql",
    ".log",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".zip",
    ".tar",
    ".gz",
    ".xlsx",
    ".webm",
    ".mp4",
}
LOCAL_FILES = {"PROJECT.md", "docs/implementation-contract.md", "docs/github-audit.md"}
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 1024 * 1024
IGNORE_PROBES = (
    ".env",
    ".env.production",
    "data/probe.csv",
    "artifacts/probe.dump",
    "outputs/probe.xlsx",
    ".venv/probe.py",
    "node_modules/probe.js",
    "backups/probe.dump",
    "probe.pem",
    "probe.log",
)
# These exact values belong only to disposable CI/test accounts, never deployments.
KNOWN_TEST_VALUES = {
    ".github/workflows/ci.yml": {
        "ci-only-password",
        "ci-only-session-secret-at-least-32-characters",
    },
    "tests/test_api.py": {
        "test-only-password",
        "test-only-session-secret-at-least-32-characters",
    },
    "tests/test_postgres.py": {"unused"},
    "tests/test_worker.py": {"unused"},
}
TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
    re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
)
QUOTED_CREDENTIAL = re.compile(
    r"""(?i)["']?\b(?:[a-z_]*(?:password|secret|api_key|access_token|auth_token)[a-z_]*)"""
    r"""["']?\s*[:=]\s*["']([^"'\r\n]+)["']"""
)
YAML_CREDENTIAL = re.compile(
    r"(?im)^[ \t]*(?:[a-z_]*(?:password|secret|api_key|access_token|auth_token)[a-z_]*)"
    r"[ \t]*:[ \t]*([^\s#'\"{}]+)[ \t]*(?:#.*)?$"
)
CREDENTIAL_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:([^@\s/]+)@", re.I)
ENV_CREDENTIAL = re.compile(
    r"(?im)^[ \t]*(?:[a-z_]*(?:password|secret|api_key|access_token|auth_token)[a-z_]*)"
    r"[ \t]*=[ \t]*([^\s#'\"{}]+)[ \t]*(?:#.*)?$"
)


@dataclass(frozen=True)
class Finding:
    path: str
    code: str
    line: int = 0

    def __str__(self):
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"BLOCK {location}: {self.code}"


def private_path(relative):
    path = PurePosixPath(relative)
    return (
        relative in LOCAL_FILES
        or any(
            part.lower() in PRIVATE_DIRS or part.lower().endswith(".egg-info")
            for part in path.parts
        )
        or (path.name.startswith(".env") and relative != ".env.example")
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or path.name in {"id_rsa", "id_ed25519", ".coverage"}
    )


def allowed_path(relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or private_path(relative):
        return False
    return (
        relative in ROOT_FILES
        or relative in PUBLIC_IMAGES
        or (
            len(path.parts) > 1
            and path.parts[0] in SOURCE_DIRS
            and path.suffix.lower() in TEXT_SUFFIXES
        )
    )


def reparse_point(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def source_files(root):
    """Yield metadata only for private paths; do not descend into them or junctions."""
    for directory, dirs, files in os.walk(root, topdown=True, followlinks=False):
        directory = Path(directory)
        kept = []
        for name in sorted(dirs):
            path = directory / name
            relative = path.relative_to(root).as_posix()
            if private_path(relative):
                continue
            if reparse_point(path):
                yield relative, "link"
            elif directory == root and name not in SOURCE_DIRS:
                yield relative, "unapproved_directory"
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            path = directory / name
            relative = path.relative_to(root).as_posix()
            if private_path(relative):
                continue
            yield relative, "link" if reparse_point(path) else "file"


def secret_findings(relative, text):
    found = set()
    for pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            found.add(
                Finding(
                    relative,
                    "possible credential/key material",
                    text.count("\n", 0, match.start()) + 1,
                )
            )
    credential_patterns = [QUOTED_CREDENTIAL, YAML_CREDENTIAL, CREDENTIAL_URL]
    if relative == ".env.example":
        credential_patterns.append(ENV_CREDENTIAL)
    for pattern in credential_patterns:
        for match in pattern.finditer(text):
            value = match[1]
            if value in KNOWN_TEST_VALUES.get(relative, set()) or "${" in value:
                continue
            if value.startswith("<") and value.endswith(">"):
                continue
            found.add(
                Finding(
                    relative,
                    "possible hardcoded credential",
                    text.count("\n", 0, match.start()) + 1,
                )
            )
    return sorted(found, key=lambda finding: (finding.line, finding.code))


def inspect_file(root, relative, content=None):
    """Policy before content: a forbidden path must never be opened."""
    if not allowed_path(relative):
        return [Finding(relative, "outside explicit public source/asset allowlist")]
    path = root / relative
    if content is None:
        if reparse_point(path):
            return [Finding(relative, "symlink/junction is not a public source file")]
        limit = MAX_IMAGE_BYTES if relative in PUBLIC_IMAGES else MAX_TEXT_BYTES
        if path.stat().st_size > limit:
            return [Finding(relative, "file exceeds publication size limit")]
        content = path.read_bytes()
    limit = MAX_IMAGE_BYTES if relative in PUBLIC_IMAGES else MAX_TEXT_BYTES
    if len(content) > limit:
        return [Finding(relative, "file exceeds publication size limit")]
    if relative in PUBLIC_IMAGES:
        return (
            []
            if content.startswith(b"\x89PNG\r\n\x1a\n")
            else [Finding(relative, "invalid PNG signature")]
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Finding(relative, "binary or non-UTF-8 source file")]
    if "\x00" in text:
        return [Finding(relative, "binary source file")]
    return secret_findings(relative, text)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30)


def inspect_blob(root, relative, oid):
    size = git(root, "cat-file", "-s", oid)
    limit = MAX_IMAGE_BYTES if relative in PUBLIC_IMAGES else MAX_TEXT_BYTES
    if size.returncode or int(size.stdout) > limit:
        return [Finding(relative, "Git blob exceeds size limit or is unreadable")]
    blob = git(root, "cat-file", "blob", oid)
    if blob.returncode:
        return [Finding(relative, "Git blob is unreadable")]
    return inspect_file(root, relative, content=blob.stdout)


def git_findings(root, require_git):
    findings = []
    result = git(root, "rev-parse", "--show-toplevel")
    if result.returncode or Path(os.fsdecode(result.stdout).strip()).resolve() != root.resolve():
        return (
            [Finding(".git", "initialize a separate project repository first")]
            if require_git
            else []
        ), "no local Git repository; index/HEAD checks not run"
    for probe in IGNORE_PROBES:
        if git(root, "check-ignore", "--no-index", "-q", "--", probe).returncode != 0:
            findings.append(
                Finding(".gitignore", f"must ignore private/runtime path pattern: {probe}")
            )
    if git(root, "check-ignore", "--no-index", "-q", "--", ".env.example").returncode == 0:
        findings.append(Finding(".gitignore", "public .env.example must not be ignored"))
    indexed = git(root, "ls-files", "--stage", "-z")
    if indexed.returncode:
        return findings + [Finding(".git", "could not read index")], "Git index unavailable"
    index_count = 0
    for entry in indexed.stdout.split(b"\x00"):
        if not entry:
            continue
        meta, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = meta.decode("ascii").split()
        relative = os.fsdecode(raw_path).replace("\\", "/")
        index_count += 1
        if not allowed_path(relative):
            findings.append(Finding(relative, "private/unapproved file included in Git index"))
            continue
        if mode not in {"100644", "100755"} or stage != "0":
            findings.append(Finding(relative, "index contains link/submodule/conflict"))
            continue
        findings.extend(inspect_blob(root, relative, oid))
    head = git(root, "ls-tree", "-rz", "--full-tree", "HEAD")
    head_count = 0
    if head.returncode == 0:
        for entry in head.stdout.split(b"\x00"):
            if not entry:
                continue
            meta, raw_path = entry.split(b"\t", 1)
            relative = os.fsdecode(raw_path).replace("\\", "/")
            head_count += 1
            if not allowed_path(relative) or not meta.startswith(
                (b"100644 blob ", b"100755 blob ")
            ):
                findings.append(
                    Finding(relative, "HEAD/archive contains private or unapproved path")
                )
            else:
                findings.extend(inspect_blob(root, relative, meta.decode("ascii").split()[2]))
    return findings, f"Git index: {index_count} paths; HEAD/archive tree: {head_count} paths"


def check(root=ROOT, require_git=False):
    findings, count = [], 0
    for relative, kind in source_files(root):
        if kind == "link":
            findings.append(Finding(relative, "symlink/junction excluded; remove from public tree"))
        else:
            count += 1
            findings.extend(inspect_file(root, relative))
    git_issues, summary = git_findings(root, require_git)
    findings.extend(git_issues)
    return (
        sorted(set(findings), key=lambda issue: (issue.path, issue.line, issue.code)),
        count,
        summary,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-git", action="store_true")
    args = parser.parse_args()
    findings, count, summary = check(require_git=args.require_git)
    for finding in findings:
        print(finding)
    print(f"Checked {count} public source/assets; {summary}.")
    print("Private runtime directories were skipped without reading their contents.")
    print(
        "FAIL"
        if findings
        else "PASS (heuristic local preflight; not a full history/security audit)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
