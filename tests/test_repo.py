"""Repository hygiene: no secrets, placeholder-only env files, consistent wording, working links."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".gate", ".sessions", ".workshop", "node_modules"}
COMPARISONS = {"README.md", "docs/faq.md"}

SECRET_PATTERNS = {
    "Arcade key": r"\barc_[A-Za-z0-9]{20,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{10,}",
    "AWS access key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
}


def repo_files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        paths = [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        paths = [p for p in ROOT.rglob("*") if p.is_file()]
    return [p for p in paths if p.is_file() and not SKIP & set(p.relative_to(ROOT).parts)]


def text_files():
    for path in repo_files():
        if path.suffix in {".lock", ".png", ".jpg", ".gif", ".pdf"}:
            continue
        try:
            yield path, path.read_text()
        except UnicodeDecodeError:
            continue


def test_no_secrets_anywhere():
    found = [f"{path.relative_to(ROOT)}: {name}" for path, text in text_files()
             for name, pattern in SECRET_PATTERNS.items() if re.search(pattern, text)]
    assert not found, found


def test_only_example_env_files():
    envs = [p.relative_to(ROOT).as_posix() for p in repo_files() if p.name.startswith(".env")]
    assert sorted(envs) == [".env.example", "mcp/.env.example"]


def test_env_examples_hold_no_values_for_secrets():
    for name in (".env.example", "mcp/.env.example"):
        for line in (ROOT / name).read_text().splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            if re.search(r"KEY|TOKEN|PASSWORD|SECRET|URI", key):
                assert value.strip() == "", f"{name}: {key} must be empty"


def test_other_frameworks_are_named_only_where_compared():
    pattern = re.compile(r"langchain|langgraph|deep[ -]?agents?", re.IGNORECASE)
    found = [path.relative_to(ROOT).as_posix() for path, text in text_files()
             if path.relative_to(ROOT).as_posix() not in COMPARISONS and pattern.search(text)
             and path.relative_to(ROOT).as_posix() != "tests/test_repo.py"]
    assert not found, found


def test_markdown_links_resolve():
    broken = []
    for path, text in text_files():
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, broken
