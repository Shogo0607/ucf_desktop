import sys
from pathlib import Path
from openai import OpenAI

from pdf.file_manager import find_unanalyzed_pdfs, save_json, save_embeddings, move_processed_pdf, create_output_directory
from pdf.converter import convert_pdf_to_images
from pdf.document_processor import process_pages_batch
from pdf.embeddings import generate_embeddings

from typing import Dict, Any, Optional, Callable


def _log(msg: str):
    """PDF 分析のログ出力。stdout を汚染しないよう stderr に書く。"""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def analyze_new_pdfs(
    database_dir: str,
    client: OpenAI,
    vision_model: str = "gpt-4.1-mini",
    summary_model: str = "gpt-4.1-mini",
    progress_callback: Optional[Callable] = None,
):
    """
    Main entry point. Finds unanalyzed PDFs in the database directory
    and processes them into JSON files.

    progress_callback(event_data: dict): called with progress updates.
    """
    _log(f"Checking for unanalyzed PDFs in {database_dir}...")
    pdf_files = find_unanalyzed_pdfs(database_dir)

    if not pdf_files:
        _log("No new PDFs to analyze.")
        return

    _log(f"Found {len(pdf_files)} PDF(s) to analyze.")
    total_files = len(pdf_files)

    for file_idx, pdf_path in enumerate(pdf_files):
        _process_single_pdf(
            pdf_path, client, vision_model, summary_model,
            progress_callback=progress_callback,
            file_index=file_idx,
            total_files=total_files,
        )

    # Signal completion
    if progress_callback:
        progress_callback({"status": "done"})


def _process_single_pdf(
    pdf_path: Path,
    client: OpenAI,
    vision_model: str,
    summary_model: str,
    progress_callback: Optional[Callable] = None,
    file_index: int = 0,
    total_files: int = 1,
):
    pdf_name = pdf_path.name
    _log(f"Processing {pdf_name}...")

    def _notify(phase: str, detail: str = "", pct: int = 0):
        if progress_callback:
            progress_callback({
                "status": "running",
                "file": pdf_name,
                "file_index": file_index,
                "total_files": total_files,
                "phase": phase,
                "detail": detail,
                "percent": pct,
            })

    # 1. Convert to images
    _notify("converting", "画像に変換中...", 0)
    images = convert_pdf_to_images(pdf_path)
    if not images:
        _log(f"  Failed to convert {pdf_name} to images. Skipping.")
        return

    total_pages = len(images)

    # 2. Process all pages in batch (image -> markdown -> summary)
    def _page_progress(phase: str, completed: int, total: int):
        if phase == "converting":
            pct = int(completed / total * 50)  # 0-50%
            _notify("converting", f"Markdown変換中 ({completed}/{total})", pct)
        else:
            pct = 50 + int(completed / total * 45)  # 50-95%
            _notify("summarizing", f"要約生成中 ({completed}/{total})", pct)

    _notify("converting", f"{total_pages}ページを処理中...", 0)
    page_data = process_pages_batch(
        images,
        client=client,
        vision_model=vision_model,
        summary_model=summary_model,
        max_concurrency=100,
        progress_callback=_page_progress,
    )

    # 3. Build JSON array: [{page, summary, content, metadata}, ...]
    _notify("saving", "保存中...", 95)
    pages_json = []
    for page_num in sorted(page_data.keys()):
        data = page_data[page_num]
        entry = {
            "page": page_num,
            "summary": data["summary"],
            "content": data["markdown"],
        }
        if "metadata" in data:
            entry["metadata"] = data["metadata"]
        pages_json.append(entry)

    # 4. Create output directory (same name as PDF stem) and save files inside
    output_dir = create_output_directory(pdf_path)

    json_filename = f"{pdf_path.stem}.json"
    json_output_path = output_dir / json_filename
    save_json(pages_json, json_output_path)
    _log(f"  Saved {len(pages_json)} pages to {json_output_path}")

    # 5. Generate and save embeddings
    _notify("embedding", "埋め込み生成中...", 96)
    try:
        embeddings_data = generate_embeddings(client, pages_json)
        embeddings_path = output_dir / f"{pdf_path.stem}_embeddings.json"
        save_embeddings(embeddings_data, embeddings_path)
        _log(f"  Saved embeddings to {embeddings_path}")
    except Exception as e:
        _log(f"  Failed to generate embeddings: {e}")

    # 6. Move original PDF into output directory and rename
    try:
        new_path = move_processed_pdf(pdf_path, output_dir)
        _log(f"  Finished {pdf_name} -> {new_path}")
    except Exception as e:
        _log(f"  Failed to move PDF: {e}")

    _notify("saving", "完了", 100)
