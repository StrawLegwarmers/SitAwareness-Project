"""Things that must stay true for the repository to be safe to publish."""
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = {".py", ".js", ".html", ".css", ".yml", ".yaml", ".md", ".txt", ".json", ".cfg", ".toml"}
SKIP = ("site/data/", "state/")      # collected news: checked by the pipeline, not by these rules


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
        files = [ROOT / f for f in out]
    except Exception:                      # not a git checkout: look at everything
        files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [p for p in files if p.suffix in TEXT and not str(p.relative_to(ROOT)).startswith(SKIP)]


SECRETS = {
    "Google API key": r"AIza[0-9A-Za-z_\-]{35}",
    "Anthropic key": r"sk-ant-[0-9A-Za-z_\-]{20,}",
    "OpenAI-style key": r"\bsk-[0-9A-Za-z]{32,}",
    "GitHub token": r"\bgh[pousr]_[0-9A-Za-z]{30,}",
    "AWS key": r"\bAKIA[0-9A-Z]{16}\b",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def test_no_secrets_in_the_repository():
    found = [f"{p.relative_to(ROOT)}: {name}" for p in tracked_files() for name, rx in SECRETS.items()
             if p.name != "test_security.py" and re.search(rx, p.read_text(encoding="utf-8", errors="ignore"))]
    assert not found, found


def test_no_personal_email_addresses():
    allowed = re.compile(r"(noreply\.github\.com|@example\.(com|org)|@users\.noreply)", re.I)
    rx = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    found = [f"{p.relative_to(ROOT)}: {m}" for p in tracked_files()
             for m in rx.findall(p.read_text(encoding="utf-8", errors="ignore")) if not allowed.search(m)
             and not m.startswith(("git@", "u@", "x@"))]
    assert not found, found


def test_workflows_never_paste_untrusted_text_into_commands():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        doc = yaml.safe_load(wf.read_text())
        for job in doc.get("jobs", {}).values():
            for step in job.get("steps", []):
                assert "github.event" not in str(step.get("run", "")), f"{wf.name}: {step.get('name')}"


def test_workflows_declare_least_privilege():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        doc = yaml.safe_load(wf.read_text())
        top = doc.get("permissions")
        assert top is not None, f"{wf.name}: set permissions explicitly"
        for name, job in doc.get("jobs", {}).items():
            perms = job.get("permissions", top) or {}
            if "id-token" in perms:
                assert name == "deploy", f"{wf.name}: only the deploy job may request id tokens"


def test_real_indicator_files_are_never_committed():
    ignored = (ROOT / ".gitignore").read_text()
    assert "/site/feeds/" in ignored and "/data/" in ignored and ".env" in ignored


def test_page_security_policy():
    html = (ROOT / "site" / "index.html").read_text()
    csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html).group(1)
    assert "script-src 'self'" in csp and "object-src 'none'" in csp and "base-uri 'none'" in csp
    assert "unsafe-eval" not in csp and "unsafe-inline" not in csp
    assert "style-src 'self'" in csp
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "no inline scripts"
    assert 'name="referrer" content="no-referrer"' in html and 'content="noindex"' in html
    js = (ROOT / "site" / "assets" / "app.js").read_text()
    assert "eval(" not in js and "new Function" not in js
    # The policy forbids inline styles, so the page must not use them (they would silently not apply)
    assert not re.search(r"\bstyle=", js + html), "use a class from style.css instead of style=\"...\""
    assert "<style" not in html


def test_actions_are_pinned_to_exact_commits():
    """A tag can be moved; a commit can't. Dependabot (.github/dependabot.yml) keeps the pins current."""
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in wf.read_text().splitlines():
            if line.strip().startswith(("uses:", "- uses:")):
                ref = line.split("uses:", 1)[1].split("#")[0].strip()
                assert re.search(r"@[0-9a-f]{40}$", ref), f"{wf.name}: {ref} is not pinned to a commit"
    assert (ROOT / ".github" / "dependabot.yml").exists()
