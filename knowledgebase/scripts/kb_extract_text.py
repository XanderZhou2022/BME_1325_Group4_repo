#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path


KB_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = KB_ROOT / "registry" / "sources.json"
TEXT_DIR = KB_ROOT / "extracted_text"
STATUS_PATH = KB_ROOT / "registry" / "extraction_status.json"


def load_sources() -> list[dict]:
    if not REGISTRY_PATH.exists():
        raise SystemExit("sources.json not found. Run kb_build_sources_registry.py first.")
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return data["sources"]


def extract_with_pymupdf(pdf_path: Path) -> list[str] | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None
    doc = fitz.open(pdf_path)
    return [page.get_text("text") for page in doc]


def pdf_page_count(pdf_path: Path) -> int:
    proc = subprocess.run(["pdfinfo", str(pdf_path)], check=True, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"Could not determine page count for {pdf_path}")


def extract_page_with_pdftotext(pdf_path: Path, page: int) -> str:
    proc = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-f", str(page), "-l", str(page), str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def extract_with_pdftotext(pdf_path: Path) -> list[str]:
    pages = pdf_page_count(pdf_path)
    return [extract_page_with_pdftotext(pdf_path, page) for page in range(1, pages + 1)]


def main() -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    statuses = []
    for source in load_sources():
        pdf_path = KB_ROOT / source["relative_path"]
        method = "pymupdf"
        pages = extract_with_pymupdf(pdf_path)
        if pages is None:
            method = "pdftotext"
            pages = extract_with_pdftotext(pdf_path)

        source_id = source["source_id"]
        empty_pages = [idx + 1 for idx, text in enumerate(pages) if not text.strip()]
        page_records = [{"page": idx + 1, "text": text} for idx, text in enumerate(pages)]
        joined_text = "\n\n".join(f"\n--- Page {idx + 1} ---\n{text}" for idx, text in enumerate(pages))

        (TEXT_DIR / f"{source_id}.txt").write_text(joined_text, encoding="utf-8")
        (TEXT_DIR / f"{source_id}.pages.json").write_text(
            json.dumps({"source_id": source_id, "pages": page_records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        statuses.append(
            {
                "source_id": source_id,
                "filename": source["filename"],
                "status": "ok" if not empty_pages else "ok_with_empty_pages",
                "method": method,
                "page_count": len(pages),
                "empty_pages": empty_pages,
                "human_review_required": True,
                "extracted_at": date.today().isoformat(),
            }
        )

    STATUS_PATH.write_text(
        json.dumps({"schema_version": "icu_agent.extraction_status.v1", "sources": statuses}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Extracted text for {len(statuses)} sources.")


if __name__ == "__main__":
    main()
