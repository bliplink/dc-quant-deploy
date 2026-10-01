#!/usr/bin/env python3
"""Check the two public API editions and optionally enforce paired changes.

The catalogs themselves are generated from the same checked OpenAPI YAML during
the Docker build. Prose still needs human review in both languages.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/public-api"
SHARED_PAGES = {"index.md", "status.md"}
REQUIRED_PAGES = {
    "index.md",
    "status.md",
    "quick-start.md",
    "authentication.md",
    "trader.md",
    "broker.md",
    "realtime.md",
    "rate-limits.md",
    "changelog.md",
}
CONTRACT_PREFIXES = ("docs/openapi/", "docs/api/")
MANIFEST = PUBLIC / "i18n-manifest.json"
NAV_FILES = (ROOT / "mkdocs.public.yml", ROOT / "mkdocs.public.zh.yml")
PUBLISHED_SOURCE_FILES = [
    ROOT / "docs/openapi/crypto-openapi-v1.yaml",
    ROOT / "docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md",
    ROOT / "docs/CRYPTO_OPEN_API_V1.zh-CN.md",
    *sorted(
        source for source in (ROOT / "docs/openapi").glob("*.md")
        if source.name not in {
            "README.zh-CN.md",
            "DEVELOPER_PORTAL_STRUCTURE.zh-CN.md",
            "EXTERNAL_GA_CHECKLIST.zh-CN.md",
        }
    ),
    *sorted((ROOT / "docs/api").glob("*.md")),
]


def page(locale: str, slug: str) -> Path:
    if locale == "en" and slug in SHARED_PAGES:
        return PUBLIC / slug
    return PUBLIC / locale / slug


def repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def git_lines(*args: str) -> set[str]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return set(result.stdout.splitlines())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_manifest() -> dict:
    published = hashlib.sha256()
    for source in PUBLISHED_SOURCE_FILES:
        published.update(repo_path(source).encode("utf-8"))
        published.update(b"\0")
        published.update(source.read_bytes())
        published.update(b"\0")
    return {
        "version": 1,
        "pairs": {
            slug: {locale: digest(page(locale, slug)) for locale in ("en", "zh")}
            for slug in sorted(REQUIRED_PAGES)
        },
        "nav": {locale: digest(source) for locale, source in zip(("en", "zh"), NAV_FILES)},
        "published_source_sha256": published.hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref", help="Git ref to compare for paired-language changes"
    )
    parser.add_argument(
        "--accept", action="store_true", help="accept reviewed changes to both languages and refresh the manifest"
    )
    args = parser.parse_args()
    errors: list[str] = []

    for locale in ("en", "zh"):
        directory = PUBLIC / locale
        actual = {item.name for item in directory.glob("*.md")}
        if locale == "en":
            actual |= SHARED_PAGES
        missing = REQUIRED_PAGES - actual
        unexpected = actual - REQUIRED_PAGES
        if missing:
            errors.append(f"{locale}: missing pages: {', '.join(sorted(missing))}")
        if unexpected:
            errors.append(f"{locale}: unpaired pages: {', '.join(sorted(unexpected))}")
        nav = NAV_FILES[0 if locale == "en" else 1].read_text(encoding="utf-8")
        for slug in sorted(REQUIRED_PAGES):
            source = page(locale, slug)
            if not source.is_file():
                continue
            contents = source.read_text(encoding="utf-8")
            if not contents.startswith("# ") or len(contents.strip()) < 120:
                errors.append(f"{repo_path(source)}: expected a non-empty H1 page")
            if slug not in nav:
                errors.append(f"{repo_path(source)}: missing from {locale} nav")

    if args.base_ref:
        try:
            changed = git_lines("diff", "--name-only", "--diff-filter=ACMRT", args.base_ref)
            changed |= git_lines("ls-files", "--others", "--exclude-standard")
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"Cannot compare with {args.base_ref}: {error.stderr.strip()}") from error

        for slug in sorted(REQUIRED_PAGES):
            en_changed = repo_path(page("en", slug)) in changed
            zh_changed = repo_path(page("zh", slug)) in changed
            if en_changed != zh_changed:
                errors.append(f"{slug}: update both English and Chinese pages together")

        nav_changed = [repo_path(source) in changed for source in NAV_FILES]
        if nav_changed[0] != nav_changed[1]:
            errors.append("navigation: update both English and Chinese configs together")

        contract_changed = any(path.startswith(CONTRACT_PREFIXES) or path in {
            "docs/DC_OPEN_API_V1_REFERENCE.zh-CN.md",
            "docs/CRYPTO_OPEN_API_V1.zh-CN.md",
        } for path in changed)
        if contract_changed:
            for locale in ("en", "zh"):
                if repo_path(page(locale, "changelog.md")) not in changed:
                    errors.append(
                        f"API contract/reference changed: update {locale} changelog.md"
                    )

    if not errors:
        snapshot = current_manifest()
        if MANIFEST.is_file():
            try:
                recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
            except (ValueError, OSError) as error:
                errors.append(f"invalid {repo_path(MANIFEST)}: {error}")
                recorded = {}
            for slug in sorted(REQUIRED_PAGES):
                old = recorded.get("pairs", {}).get(slug, {})
                new = snapshot["pairs"][slug]
                if (old.get("en") != new["en"]) != (old.get("zh") != new["zh"]):
                    errors.append(f"{slug}: one language changed since the accepted manifest")
            old_nav = recorded.get("nav", {})
            new_nav = snapshot["nav"]
            if (old_nav.get("en") != new_nav["en"]) != (old_nav.get("zh") != new_nav["zh"]):
                errors.append("navigation: one language changed since the accepted manifest")
            if recorded.get("published_source_sha256") != snapshot["published_source_sha256"]:
                old_log = recorded.get("pairs", {}).get("changelog.md", {})
                new_log = snapshot["pairs"]["changelog.md"]
                if any(old_log.get(locale) == new_log[locale] for locale in ("en", "zh")):
                    errors.append("published API source changed: update both changelog pages")
            if recorded != snapshot and not args.accept:
                errors.append("manifest is stale; review both languages, then run check --accept")
        elif not args.accept:
            errors.append(f"missing {repo_path(MANIFEST)}; run check --accept after review")

    if errors:
        for error in errors:
            print(f"[public-api-i18n] ERROR: {error}")
        raise SystemExit(1)
    if args.accept:
        MANIFEST.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[public-api-i18n] accepted {repo_path(MANIFEST)}")
    print(
        f"[public-api-i18n] PASS: {len(REQUIRED_PAGES)} paired pages; "
        + (f"changes checked against {args.base_ref}" if args.base_ref else "structural check")
    )


if __name__ == "__main__":
    main()
