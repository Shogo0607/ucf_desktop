import io
import sys
import base64
import json
from typing import List, Dict, Any, Optional, Callable
from PIL import Image
from dotenv import load_dotenv
from openai import OpenAI
import concurrent.futures
from skills.rag.utils.prompt_loader import PromptLoader

load_dotenv()

loader = PromptLoader()


def _pil_image_to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _image_to_markdown(client: OpenAI, model: str, data_url: str, page_number: int) -> str:
    """Vision API で画像を Markdown に変換する。"""
    instruction = f"Page {page_number:03}: {loader.get_prompt('PDF_EXTRACTION_PAGE_INSTRUCTIONS')}"
    token_param = "max_completion_tokens" if model.startswith(("gpt-5", "o1", "o3", "o4")) else "max_tokens"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": loader.get_prompt("PDF_EXTRACTION_SYSTEM_PROMPT")},
            {"role": "user", "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ],
        **{token_param: 4096},
        timeout=60,
    )
    return response.choices[0].message.content or ""


def _markdown_to_summary(client: OpenAI, model: str, markdown: str) -> dict:
    """Markdown テキストから要約を生成する。"""
    snippet = markdown.strip()
    if len(snippet) > 6000:
        snippet = snippet[:6000] + "\n...[truncated]"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": loader.get_prompt("SUMMARY_SYSTEM_PROMPT")},
            {"role": "user", "content": f"以下はページの内容です。\n\n```markdown\n{snippet}\n```"},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def process_pages_batch(
    images: List[Image.Image],
    client: OpenAI,
    vision_model: str = "gpt-4.1-mini",
    summary_model: str = "gpt-4.1-mini",
    max_concurrency: int = 100,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[int, Dict[str, str]]:
    """
    Processes a batch of images: Image -> Markdown -> Summary.
    Returns a dict: {page_num: {"markdown": str, "summary": str}}

    progress_callback(phase, completed, total): called on each step completion.
      phase: "converting" or "summarizing"
    """
    # Prepare base64 data URLs
    vision_inputs = []
    for i, img in enumerate(images):
        vision_inputs.append({
            "data_url": _pil_image_to_data_url(img),
            "page_number": i + 1
        })

    total = len(images)

    markdown_results = [None] * total
    summary_results = [None] * total

    # 1. Image -> Markdown (concurrent)
    def _convert_page(item):
        return _image_to_markdown(client, vision_model, item["data_url"], item["page_number"])

    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_convert_page, item): i for i, item in enumerate(vision_inputs)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                markdown_results[index] = future.result()
            except Exception as e:
                sys.stderr.write(f"Error processing page {index+1}: {e}\n")
                markdown_results[index] = ""
            completed_count += 1
            if progress_callback:
                progress_callback("converting", completed_count, total)

    # 2. Markdown -> Summary (concurrent)
    def _summarize_page(md):
        return _markdown_to_summary(client, summary_model, md)

    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_summarize_page, md): i for i, md in enumerate(markdown_results)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                summary_results[index] = future.result()
            except Exception as e:
                sys.stderr.write(f"Error summarizing page {index+1}: {e}\n")
                summary_results[index] = {}
            completed_count += 1
            if progress_callback:
                progress_callback("summarizing", completed_count, total)

    results = {}
    for i in range(total):
        page_num = i + 1
        results[page_num] = {
            "markdown": markdown_results[i],
            "summary": summary_results[i].get("summary", ""),
        }

    return results
