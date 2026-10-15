#!/usr/bin/env python3
"""The ScreenSafe pack catalog: checks packs.toml, writes the pages people browse, and verifies listed packs.

    python3 scripts/catalog.py generate            # write README.md and packs/<id>.md from packs.toml
    python3 scripts/catalog.py check               # check every entry, and that the pages are up to date
    python3 scripts/catalog.py verify [ID ...]     # fetch each pack as an install does, and check its files and
                                                   # the pack itself with ScreenSafe's renderer (all, if no IDs)
    python3 scripts/catalog.py changes BASE.toml   # what a pull request adds or changes, against packs.toml before it

With SCREENSAFE_FRAMES set to a folder, `verify` also renders frames from across each pack's loop there, beside its
own preview, so a reviewer can see that the preview is true to the pack.

packs.toml is the only thing edited by hand. Everything a person browses is generated from it, so a listing can't
say anything its entry doesn't. Previews and art stay in their makers' repositories: pages show them from there, at
the approved commit, and nothing of theirs is copied here. Needs Python 3.11 or later and nothing else; `verify`
also needs network access, and the renderer (see RENDERER below).
"""
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "packs.toml"
PAGES = ROOT / "packs"
README = ROOT / "README.md"

PLUGIN = "https://github.com/jeremydixon22/omarchy-screensafe"
PACKS_DIR = "~/.config/omarchy/screensafe/packs"

# The renderer packs are checked with: ScreenSafe's own binaries, at a pinned commit of the plugin, by their digests.
RENDERER = {
    "commit": "420eaa89d0878ddaef6e8163be6e73ed6e8e1dd3",
    "x86_64": "af9a3d8d7eeff56d1b87d24d86d5b5f47e3ee146bce9fcdf3082a2709899a4ce",
    "aarch64": "0040294ec26e72925d93a79852789b1bdad4b1a94b3c8d2c55972b87fc23303f",
}

LICENSES = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "MIT": "https://opensource.org/license/mit",
}
FIELDS = {"id", "name", "author", "contact", "repository", "path", "commit", "license", "preview", "description",
          "format", "added", "provenance"}
# What a pack folder may hold, by extension; a few repository files besides. Hidden files are never installed.
PACK_FILES = {".toml", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".ttf", ".otf"}
OTHER_FILES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "README.md"}
PACK_BYTES = 96 * 1024 * 1024
FILE_BYTES = 32 * 1024 * 1024
DOWNLOAD_BYTES = 128 * 1024 * 1024

ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
REPO = re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")
SEGMENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class Problem(Exception):
    pass


# ---- entries

def load():
    try:
        data = tomllib.loads(CATALOG.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise Problem(f"packs.toml: {e}")
    unknown = set(data) - {"pack", "delisted"}
    if unknown:
        raise Problem(f"packs.toml: unknown table {sorted(unknown)[0]!r}; only [[pack]] and [[delisted]]")
    packs = data.get("pack", [])
    if not isinstance(packs, list):
        raise Problem("packs.toml: `pack` must be an array of tables ([[pack]])")
    return packs, data.get("delisted", [])


def text(entry, key, most, one_line=True):
    v = entry.get(key)
    if not isinstance(v, str) or not v.strip():
        raise Problem(f"`{key}` is required")
    if len(v) > most:
        raise Problem(f"`{key}` is longer than {most} characters")
    if one_line and ("\n" in v or "\r" in v):
        raise Problem(f"`{key}` must be one line")
    if any(ord(c) < 32 and c not in "\n" for c in v):
        raise Problem(f"`{key}` has control characters")
    if "<" in v or ">" in v:
        raise Problem(f"`{key}` can't contain < or >")
    return v.strip()


def check_entry(e):
    """Checks one entry's fields, returning the problems found."""
    problems = []
    extra = set(e) - FIELDS
    if extra:
        problems.append(f"unknown field `{sorted(extra)[0]}`")
    if not ID.match(str(e.get("id", ""))):
        problems.append("`id` must be 1 to 40 lowercase letters, digits and dashes, not starting or ending with a dash")
    for key, most, one_line in (("name", 40, True), ("author", 60, True), ("description", 300, True),
                                ("provenance", 2000, False)):
        try:
            text(e, key, most, one_line)
        except Problem as p:
            problems.append(str(p))
    if not str(e.get("contact", "")).startswith("https://github.com/"):
        problems.append("`contact` must be a https://github.com/ address")
    if not REPO.match(str(e.get("repository", ""))):
        problems.append("`repository` must be https://github.com/OWNER/REPOSITORY")
    if not COMMIT.match(str(e.get("commit", ""))):
        problems.append("`commit` must be the full 40-character commit, in lowercase")
    if e.get("license") not in LICENSES:
        problems.append(f"`license` must be one of {', '.join(LICENSES)}")
    if e.get("format") != 1:
        problems.append("`format` must be 1")
    added = e.get("added")
    if not isinstance(added, datetime.date) or isinstance(added, datetime.datetime):
        problems.append("`added` must be a date, like 2026-11-02")
    path = e.get("path", ".")
    if not isinstance(path, str) or (path != "." and not all(SEGMENT.match(s) for s in path.split("/"))):
        problems.append("`path` must be \".\" or a folder within the repository, like screensafe or packs/aquarium")
    preview = e.get("preview", "preview.png")
    if (not isinstance(preview, str) or not SEGMENT.match(preview)
            or Path(preview).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}):
        problems.append("`preview` must be an image file name in the pack's folder")
    return problems


def kind_of(data):
    """What a file is, by its contents: an image or font format, or text."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return "font"
    try:
        text_ = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text" if "\x00" not in text_ else None


# What each file name's extension must turn out to be.
EXPECTED = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".ttf": "font", ".otf": "font",
            ".toml": "text", ".txt": "text", ".md": "text", "": "text"}


def check_delisted(delisted):
    problems = []
    for i, d in enumerate(delisted if isinstance(delisted, list) else [None]):
        where = f"delisted {i + 1}"
        if not isinstance(d, dict):
            problems.append(f"{where}: `delisted` must be an array of tables ([[delisted]])")
            continue
        if not ID.match(str(d.get("id", ""))):
            problems.append(f"{where}: `id` is required")
        if not isinstance(d.get("delisted"), datetime.date):
            problems.append(f"{where}: `delisted` must be the date it was delisted")
        if not isinstance(d.get("reason"), str) or not d["reason"].strip():
            problems.append(f"{where}: `reason` is required")
    return problems


def check_all(packs):
    problems = []
    seen = set()
    for i, e in enumerate(packs):
        where = f"pack {i + 1} ({e.get('id', '?')})"
        if not isinstance(e, dict):
            problems.append(f"{where}: not a table")
            continue
        problems += [f"{where}: {p}" for p in check_entry(e)]
        if e.get("id") in seen:
            problems.append(f"{where}: `id` is used twice")
        seen.add(e.get("id"))
    ids = [e.get("id") for e in packs if isinstance(e, dict)]
    if ids != sorted(ids, key=lambda s: str(s)):
        problems.append("entries must be in order of `id`")
    return problems


# ---- where a pack comes from, and how it's installed

def parts(e):
    owner, repo = REPO.match(e["repository"]).groups()
    path = e.get("path", ".")
    return owner, repo, path


def tarball(e):
    owner, repo, _ = parts(e)
    return f"https://codeload.github.com/{owner}/{repo}/tar.gz/{e['commit']}"


def raw(e, name):
    owner, repo, path = parts(e)
    folder = "" if path == "." else path + "/"
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{e['commit']}/{folder}{name}"


def tree(e):
    owner, repo, path = parts(e)
    return f"https://github.com/{owner}/{repo}/tree/{e['commit']}" + ("" if path == "." else "/" + path)


def strip(e):
    _, _, path = parts(e)
    return 1 if path == "." else 1 + len(path.split("/"))


def member(e):
    _, _, path = parts(e)
    return None if path == "." else f"*/{path}/*"


def install_command(e):
    """One line to paste: the pack's folder at the approved commit, from GitHub's own archive of that commit, into
    the packs folder. Hidden files are left out. Nothing runs from the pack."""
    dest = f"{PACKS_DIR}/{e['id']}"
    tar = f"tar -xz --no-same-owner --exclude='.*' -C {dest} --strip-components={strip(e)}"
    if member(e):
        tar += f" --wildcards '{member(e)}'"
    return f"mkdir -p {dest} && curl -fsSL {tarball(e)} | {tar}"


# ---- pages

def cell(e):
    preview = raw(e, e.get("preview", "preview.png"))
    return (f'<a href="packs/{e["id"]}.md"><img src="{preview}" alt="{e["name"]}" width="280"></a><br>'
            f'<a href="packs/{e["id"]}.md"><b>{e["name"]}</b></a><br><sub>by {e["author"]}</sub>')


def readme(packs):
    out = [README_HEAD]
    if packs:
        out.append(f"## {len(packs)} pack{'s' if len(packs) != 1 else ''}\n")
        out.append("Pick one to see it, and copy the one line that installs it.\n")
        out.append("| | | |\n|:---:|:---:|:---:|")
        for i in range(0, len(packs), 3):
            cells = [cell(e) for e in packs[i:i + 3]]
            out.append("| " + " | ".join(cells + [""] * (3 - len(cells))) + " |")
        out.append("")
        out.append("<details>\n<summary><b>All packs, as a list</b></summary>\n")
        out.append("| Pack | By | License | Added |\n|---|---|---|---|")
        for e in packs:
            out.append(f"| [{e['name']}](packs/{e['id']}.md) | {e['author']} | {e['license']} | {e['added']} |")
        out.append("\n</details>\n")
    else:
        out.append(README_EMPTY)
    out.append(README_TAIL)
    return "\n".join(out)


def page(e):
    lic = e["license"]
    return f"""<!-- Generated from packs.toml by scripts/catalog.py; edit the entry, not this page. -->

# {e['name']}

<p align="center"><img src="{raw(e, e.get('preview', 'preview.png'))}" alt="{e['name']}" width="720"></p>

{e['description']}

| | |
|---|---|
| **By** | [{e['author']}]({e['contact']}) |
| **License** | [{lic}]({LICENSES[lic]}) |
| **Source** | [{parts(e)[0]}/{parts(e)[1]}]({tree(e)}) at `{e['commit'][:12]}` |
| **Listed** | {e['added']} |

## Install

Paste this into a terminal. It copies the pack's folder, exactly as it was reviewed, into your packs folder:

```sh
{install_command(e)}
```

Then open ScreenSafe's panel: **{e['name']}** is in the list. Like every pack, it's only data: ScreenSafe's renderer
checks it before showing it, and nothing in it ever runs.

**To update** when a newer version is listed, delete `{PACKS_DIR}/{e['id']}` and install again.
**To remove** it, delete that folder.

## Where it comes from

{e['provenance'].strip()}

---

<sub>[← All packs](../README.md) · [Report a problem with this pack](https://github.com/jeremydixon22/omarchy-screensafe-packs/issues/new?template=report-a-pack.yml&title=%5B{e['id']}%5D%20)</sub>
"""


README_HEAD = f"""<p align="center">
  <img src="docs/shield.png" width="80" alt="ScreenSafe's shield">
</p>

<h1 align="center">ScreenSafe packs</h1>

<p align="center">
  <b>Screensavers made by the community, for <a href="{PLUGIN}">ScreenSafe</a> on Omarchy.</b><br>
  Every pack here is data, not code, reviewed at an exact commit, and installed with one line you can read.
</p>

<!-- Generated from packs.toml by scripts/catalog.py; edit packs.toml, not this page. -->
"""

README_EMPTY = """## No packs yet

The catalog has just opened, and the first listing could be yours. ScreenSafe comes with
[fifteen packs of its own](https://github.com/jeremydixon22/omarchy-screensafe#the-packs) in the meantime.
"""

README_TAIL = f"""## How it works

- **Packs stay with their makers.** Each lives in its maker's own public repository. This catalog lists it at the
  exact commit that was reviewed, and copies nothing: pages show the maker's own preview, from that commit.
- **Installing is one line.** Each pack's page has it: it downloads that commit from GitHub and copies the pack's
  folder into `{PACKS_DIR}/`. ScreenSafe never fetches anything itself.
- **Every pack is checked.** Each listing is checked automatically with ScreenSafe's own renderer (every rule, its
  cost, and flashing over up to 600 seconds of its loop) and [reviewed by a person](docs/REVIEWING.md) for rights, content and
  accuracy before it's listed. Every listed pack is checked again each week.

## Share yours

Make a pack ([Making a screensaver]({PLUGIN}/blob/main/docs/MAKING.md) has the way in, and ScreenSafe's agent skill can
help), put it in a public GitHub repository, and open a pull request adding its entry to `packs.toml`.
[CONTRIBUTING.md](CONTRIBUTING.md) has the steps, and [Community packs]({PLUGIN}/blob/main/docs/COMMUNITY.md) the
whole process.

## Something wrong?

[Report a pack](https://github.com/jeremydixon22/omarchy-screensafe-packs/issues/new?template=report-a-pack.yml) that
doesn't work, doesn't look like its preview, or shouldn't be here. A maker can ask for their pack to be delisted at any
time, and it will be.
"""


def generated(packs):
    files = {README: readme(packs)}
    for e in packs:
        files[PAGES / f"{e['id']}.md"] = page(e)
    return files


def stale(packs):
    """Generated files that differ from what packs.toml gives, and pages for packs no longer listed."""
    files = generated(packs)
    out = [p for p, body in files.items() if not p.exists() or p.read_text(encoding="utf-8") != body]
    if PAGES.exists():
        out += [p for p in PAGES.glob("*.md") if p not in files]
    return files, out


# ---- verifying a listed pack, as it would be installed

def fetch(url, most):
    req = urllib.request.Request(url, headers={"User-Agent": "screensafe-packs-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(most + 1)
    if len(data) > most:
        raise Problem(f"{url} is larger than {most // (1024 * 1024)} MiB")
    return data


def extract(e, archive, dest):
    """Extracts the pack's folder from the archive the way the install line does, refusing anything but plain files
    and folders. Returns the files extracted, by path within the pack."""
    n = strip(e)
    _, _, path = parts(e)
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as t:
        for m in t.getmembers():
            names = m.name.split("/")
            if len(names) <= n or (path != "." and names[1:n] != path.split("/")):
                continue
            rel = names[n:]
            if any(s.startswith(".") for s in rel):
                continue
            if m.issym() or m.islnk() or not (m.isfile() or m.isdir()):
                raise Problem(f"{'/'.join(rel)}: links and special files aren't allowed")
            if m.isdir():
                continue
            relpath = "/".join(rel)
            ext = Path(relpath).suffix.lower()
            if ext not in PACK_FILES and relpath not in OTHER_FILES:
                raise Problem(f"{relpath}: only {', '.join(sorted(PACK_FILES))} files belong in a pack")
            if m.mode & 0o111:
                raise Problem(f"{relpath}: executable files aren't allowed")
            if m.size > FILE_BYTES:
                raise Problem(f"{relpath}: larger than {FILE_BYTES // (1024 * 1024)} MiB")
            total += m.size
            if total > PACK_BYTES:
                raise Problem(f"the pack is larger than {PACK_BYTES // (1024 * 1024)} MiB")
            data = t.extractfile(m).read()
            expected = EXPECTED.get(ext if relpath not in OTHER_FILES or ext else "")
            if kind_of(data) != expected:
                raise Problem(f"{relpath}: its contents aren't what its name says ({expected or 'text'})")
            out = dest / relpath
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            files[relpath] = data
    if "screensafe.toml" not in files:
        raise Problem(f"no screensafe.toml in {path!r} at {e['commit'][:12]}")
    return files


def renderer():
    """ScreenSafe's renderer at the pinned commit, checked against its digest, cached beside the repository."""
    arch = os.uname().machine
    if arch not in ("x86_64", "aarch64"):
        raise Problem(f"no renderer for {arch}")
    cache = Path(os.environ.get("SCREENSAFE_RENDERER_CACHE", ROOT / ".cache"))
    path = cache / f"screensafe-{arch}-{RENDERER['commit'][:12]}"
    if not path.exists():
        data = fetch(f"https://raw.githubusercontent.com/jeremydixon22/omarchy-screensafe/{RENDERER['commit']}/bin/screensafe-{arch}", 16 << 20)
        if hashlib.sha256(data).hexdigest() != RENDERER[arch]:
            raise Problem("the renderer downloaded doesn't match its pinned digest")
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755)
    if hashlib.sha256(path.read_bytes()).hexdigest() != RENDERER[arch]:
        raise Problem(f"{path} doesn't match its pinned digest; delete it and run again")
    return path


def verify(e, binary):
    with tempfile.TemporaryDirectory(prefix="screensafe-pack-") as tmp:
        dest = Path(tmp) / e["id"]
        dest.mkdir()
        files = extract(e, fetch(tarball(e), DOWNLOAD_BYTES), dest)
        preview = e.get("preview", "preview.png")
        if preview not in files:
            raise Problem(f"its preview, {preview}, isn't in the pack's folder")
        if not any(n.startswith("LICENSE") for n in files):
            license_at_root = fetch_ok(raw({**e, "path": "."}, "LICENSE"))
            if not license_at_root:
                raise Problem("no LICENSE in the pack's folder or at the repository's root")
        manifest = tomllib.loads(files["screensafe.toml"].decode("utf-8"))
        for key in ("name", "author", "license", "description"):
            theirs = str(manifest.get(key, "")).strip()
            if key == "license" and theirs != e["license"]:
                raise Problem(f"the pack's license is {theirs!r}, but the entry says {e['license']!r}")
            if key in ("name", "description") and theirs != e[key]:
                raise Problem(f"the entry's {key} must match the pack's own: {theirs!r}")
        results = []
        length = None
        for size in ("960x540", "2304x1440"):
            r = subprocess.run([str(binary), "check", str(dest), "--size", size, "--seconds", "600"],
                               capture_output=True, text=True, timeout=1800)
            try:
                report = json.loads(r.stdout)
            except json.JSONDecodeError:
                raise Problem(f"the renderer's check failed: {(r.stderr or r.stdout).strip()[-300:]}")
            if not report.get("ok"):
                raise Problem(f"check: {report.get('error', 'failed')}")
            flash = report.get("flash", {})
            if not flash.get("passes"):
                raise Problem(f"flashes past the limit at {size}: {flash.get('flashes')}")
            results.append(f"{size}: {flash.get('drawMsPerFrame', 0):.1f} ms a frame, slowest {flash.get('slowestDrawMs', 0):.0f} ms")
            length = report.get("length", length)
        frames = os.environ.get("SCREENSAFE_FRAMES")
        if frames:
            out = Path(frames)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{e['id']}-preview{Path(preview).suffix.lower()}").write_bytes(files[preview])
            for k in range(6):
                at = (k + 0.5) / 6 * float(length or 30)
                subprocess.run([str(binary), "render", str(dest), "--time", f"{at:.2f}", "--size", "960x540",
                                "--out", str(out / f"{e['id']}-{k + 1}-{at:05.1f}s.png")],
                               capture_output=True, timeout=300, check=True)
        return results, sorted(files)


def changes(packs, base_path):
    """A summary for a pull request: each pack it adds, updates or removes, and for an update, the files of the pack's
    folder that changed between the commit approved before and the new one."""
    try:
        base = tomllib.loads(Path(base_path).read_text(encoding="utf-8")).get("pack", [])
    except (OSError, tomllib.TOMLDecodeError):
        base = []
    before = {e.get("id"): e for e in base if isinstance(e, dict)}
    now = {e.get("id"): e for e in packs}
    lines = []
    for pid in sorted(set(before) | set(now), key=str):
        old, new = before.get(pid), now.get(pid)
        if old == new:
            continue
        if old is None:
            lines.append(f"- **Adds** `{pid}`: {new.get('name')} by {new.get('author')}, at `{new.get('commit')}`")
        elif new is None:
            lines.append(f"- **Removes** `{pid}`")
        elif old.get("commit") == new.get("commit"):
            fields = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            lines.append(f"- **Edits** `{pid}`'s entry: {', '.join(f'`{f}`' for f in fields)}")
        else:
            lines.append(f"- **Updates** `{pid}` from `{old.get('commit')}` to `{new.get('commit')}`")
            try:
                owner, repo, path = parts(new)
                api = f"https://api.github.com/repos/{owner}/{repo}/compare/{old['commit']}...{new['commit']}"
                diff = json.loads(fetch(api, 8 << 20))
                prefix = "" if path == "." else path + "/"
                changed = [f for f in diff.get("files", []) if f.get("filename", "").startswith(prefix)]
                for f in changed[:100]:
                    lines.append(f"  - {f.get('status')}: `{f['filename'][len(prefix):]}`")
                if not changed:
                    lines.append("  - no files in the pack's folder changed")
            except Exception as err:
                lines.append(f"  - couldn't list the changed files: {err}")
    return "\n".join(["### Pack changes", ""] + (lines or ["No packs added, updated or removed."]))


def fetch_ok(url):
    try:
        fetch(url, 1 << 20)
        return True
    except Exception:
        return False


# ---- commands

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "check"
    try:
        packs, delisted = load()
    except Problem as p:
        print(p, file=sys.stderr)
        return 1
    if cmd == "generate":
        problems = check_all(packs)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        files, old = stale(packs)
        for p in old:
            if p in files:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(files[p], encoding="utf-8")
            else:
                p.unlink()
            print(f"wrote {p.relative_to(ROOT)}" if p in files else f"removed {p.relative_to(ROOT)}")
        return 0
    if cmd == "check":
        problems = check_all(packs) + check_delisted(delisted)
        if not problems:
            _, old = stale(packs)
            problems += [f"{p.relative_to(ROOT)} is out of date; run `python3 scripts/catalog.py generate`" for p in old]
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(f"{len(packs)} entr{'y' if len(packs) == 1 else 'ies'}, all well formed; pages up to date")
        return 0
    if cmd == "verify":
        wanted = set(argv[2:])
        chosen = [e for e in packs if not wanted or e.get("id") in wanted]
        missing = wanted - {e.get("id") for e in packs}
        if missing:
            print(f"not in packs.toml: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
        problems = check_all(chosen)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        failed = 0
        binary = renderer() if chosen else None
        for e in chosen:
            try:
                results, files = verify(e, binary)
                print(f"✓ {e['id']}: {len(files)} files; " + "; ".join(results))
            except (Problem, OSError, subprocess.TimeoutExpired, tarfile.TarError, tomllib.TOMLDecodeError, UnicodeDecodeError) as p:
                print(f"✗ {e['id']}: {p}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0
    if cmd == "changes" and len(argv) == 3:
        print(changes(packs, argv[2]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
