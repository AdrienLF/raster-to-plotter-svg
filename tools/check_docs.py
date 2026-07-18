#!/usr/bin/env python3
"""Check the PlotterForge manual for broken or stale documentation."""

from __future__ import annotations

import argparse
import re
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "web" / "static" / "docs"
ACTIVE_COPY = (ROOT / "README.md", ROOT / "FEATURES.md", ROOT / "docs" / "product-roadmap.md")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag in {"a", "link"} and values.get("href"):
            self.refs.append(("href", values["href"]))
        if tag in {"img", "script"} and values.get("src"):
            self.refs.append(("src", values["src"]))
        if tag == "img":
            self.images.append(values)


def _local_path(page: Path, reference: str) -> Path | None:
    parts = urlsplit(reference)
    if parts.scheme or parts.netloc or reference.startswith(("mailto:", "tel:", "data:")):
        return None
    if not parts.path:
        return page
    return (page.parent / unquote(parts.path)).resolve()


def _png_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as source:
        header = source.read(24)
    if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", header[16:24])
    return None


def _registered_pages() -> set[str]:
    source = (DOCS / "docs.js").read_text(encoding="utf-8")
    return set(re.findall(r'href:\s*"([^"]+\.html)"', source))


def check_docs() -> list[str]:
    errors: list[str] = []
    pages = sorted(DOCS.glob("*.html"))
    page_names = {page.name for page in pages}
    registered = _registered_pages()

    for missing in sorted(page_names - registered):
        errors.append(f"unregistered manual page: {missing}")
    for missing in sorted(registered - page_names):
        errors.append(f"navigation points to missing page: {missing}")

    parsers: dict[Path, AssetParser] = {}
    for page in pages:
        parser = AssetParser()
        parser.feed(page.read_text(encoding="utf-8"))
        parsers[page] = parser

        for attr, reference in parser.refs:
            target = _local_path(page, reference)
            if target is not None and not target.is_file():
                errors.append(f"{page.name}: broken {attr} {reference}")
                continue
            fragment = urlsplit(reference).fragment
            if fragment:
                anchor_page = target if target and target.suffix == ".html" else page
                anchor_parser = parsers.get(anchor_page)
                if anchor_parser is None and anchor_page.is_file():
                    anchor_parser = AssetParser()
                    anchor_parser.feed(anchor_page.read_text(encoding="utf-8"))
                if anchor_parser is not None and unquote(fragment) not in anchor_parser.ids:
                    errors.append(f"{page.name}: missing anchor #{fragment} in {anchor_page.name}")

        for image in parser.images:
            source = image.get("src") or ""
            alt = image.get("alt")
            if alt is None or not alt.strip():
                errors.append(f"{page.name}: image needs useful alt text: {source}")
            target = _local_path(page, source)
            if target and target.is_file() and target.suffix.lower() == ".png":
                size = _png_size(target)
                if size is None:
                    errors.append(f"{page.name}: invalid PNG: {source}")
                elif min(size) < 64:
                    errors.append(f"{page.name}: image is too small to document the UI: {source} ({size[0]}x{size[1]})")

    # Anchor checks above may see a linked page before it has been parsed. Re-run
    # cross-page fragments now that every page parser is available.
    for page, parser in parsers.items():
        for _, reference in parser.refs:
            fragment = urlsplit(reference).fragment
            target = _local_path(page, reference)
            if fragment and target in parsers and unquote(fragment) not in parsers[target].ids:
                message = f"{page.name}: missing anchor #{fragment} in {target.name}"
                if message not in errors:
                    errors.append(message)

    stale_count = re.compile(r"\b(?:42|43|49)\s+(?:built-in\s+)?(?:PFMs?|path-finding styles?)\b", re.IGNORECASE)
    for path in (*ACTIVE_COPY, *pages):
        text = path.read_text(encoding="utf-8")
        if stale_count.search(text):
            errors.append(f"stale PFM count in {path.relative_to(ROOT)}")

    from tools.build_docs_reference import render_reference

    if (DOCS / "reference.html").read_text(encoding="utf-8") != render_reference():
        errors.append("reference.html is stale; run tools/build_docs_reference.py")

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    errors = check_docs()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Documentation health check passed ({len(list(DOCS.glob('*.html')))} pages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
