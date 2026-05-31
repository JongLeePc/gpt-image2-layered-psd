#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageOps
import numpy as np


SKILL_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = SKILL_ROOT / "projects"
BUNDLED_IMAGE2PSD = SKILL_ROOT / "scripts" / "image2psd.py"
LEGACY_BGGG_ROOT = Path.home() / ".codex" / "skills" / "bggg-creator-image2psd"
LEGACY_IMAGE2PSD = LEGACY_BGGG_ROOT / "scripts" / "image2psd.py"

OPENAI_BASE_URL = (os.environ.get("GPT_IMAGE2_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")


RESTORE_PROMPT = """Restore and upscale this image for PSD decomposition.
Preserve the exact composition, all text, product identity, layout, aspect ratio,
colors, and relative positions. Remove compression artifacts and improve clarity.
Do not add new objects. Do not remove objects. Do not translate, rewrite, or
redesign text."""


ANALYSIS_PROMPT = """Analyze this restored image for semantic PSD layer generation.
Return JSON only. Do not wrap in markdown.

Required JSON schema:
{
  "canvas": {"width": number, "height": number},
  "summary": "short description",
  "layers": [
    {
      "name": "Layer name",
      "type": "background|subject|title_text|info_text|icon|decoration|shadow|foreground",
      "bbox": [x1, y1, x2, y2],
      "order": number,
      "editable_text_candidate": boolean,
      "text": "exact text if visible, otherwise empty string",
      "extraction_prompt": "strict prompt for extracting this element as a transparent full-canvas PNG"
    }
  ]
}

Rules:
- Identify semantic elements, not color clusters.
- Include background, main subject/product, title text, information text, icons,
  decorative elements, foreground body parts/props, and shadows when visible.
- Include small but meaningful UI/graphic parts such as logos, arrows, labels,
  dimensions, photo cards, swatches, wheels, platforms, stairs, and shadows.
- Each layer must be one semantic element, not a rectangular crop of the poster.
- Do not merge unrelated nearby objects into one layer just because they touch.
- Bboxes must use pixel coordinates in the image coordinate system.
- Layer order must be bottom-to-top.
- Do not invent text. If text is uncertain, state uncertainty in the text field."""


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "image2_psd"


def require_api_key() -> str:
    key = os.environ.get("GPT_IMAGE2_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit(
            "GPT_IMAGE2_API_KEY or OPENAI_API_KEY is missing. Set it before running this skill. "
            "This workflow directly calls OpenAI image APIs and will not fake AI output."
        )
    return key


def require_base_url() -> str:
    if not OPENAI_BASE_URL:
        raise SystemExit(
            "GPT_IMAGE2_BASE_URL or OPENAI_BASE_URL is missing. Set it to your third-party "
            "OpenAI-compatible base URL, for example https://your-host/v1. If you explicitly "
            "want official OpenAI, set GPT_IMAGE2_BASE_URL=https://api.openai.com/v1."
        )
    return OPENAI_BASE_URL


def resolve_image2psd_script() -> Path:
    configured = os.environ.get("GPT_IMAGE2_PSD_WRITER")
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.exists():
            return path
        raise SystemExit(f"Configured PSD writer was not found: {path}")
    if BUNDLED_IMAGE2PSD.exists():
        return BUNDLED_IMAGE2PSD
    if LEGACY_IMAGE2PSD.exists():
        return LEGACY_IMAGE2PSD
    raise SystemExit(f"PSD writer not found. Expected bundled script: {BUNDLED_IMAGE2PSD}")


def headers_json(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def headers_auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def unique_project_dir(date_prefix: str, slug: str) -> Path:
    base = PROJECTS_ROOT / f"{date_prefix}_{slug}"
    if not base.exists():
        return base
    idx = 2
    while True:
        candidate = PROJECTS_ROOT / f"{date_prefix}_{slug}_{idx}"
        if not candidate.exists():
            return candidate
        idx += 1


def read_b64_image(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def extract_text_from_response(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    chunks: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if isinstance(text, str):
                chunks.append(text)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload.get("output"))
    return "\n".join(chunks).strip()


def parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def call_responses_analysis(api_key: str, model: str, image_path: Path) -> dict[str, Any]:
    body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": ANALYSIS_PROMPT},
                    {"type": "input_image", "image_url": read_b64_image(image_path)},
                ],
            }
        ],
    }
    response = requests.post(
        f"{OPENAI_BASE_URL}/responses",
        headers=headers_json(api_key),
        data=json.dumps(body),
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Responses API failed: {response.status_code} {response.text}")
    text = extract_text_from_response(response.json())
    return parse_json_text(text)


def call_image_edit(
    api_key: str,
    model: str,
    image_path: Path,
    prompt: str,
    output_path: Path,
    *,
    size: str,
    transparent: bool,
    quality: str,
) -> None:
    data = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    if transparent:
        data["background"] = "transparent"

    with image_path.open("rb") as handle:
        files = {"image[]": (image_path.name, handle, mimetypes.guess_type(image_path.name)[0] or "image/png")}
        response = requests.post(
            f"{OPENAI_BASE_URL}/images/edits",
            headers=headers_auth(api_key),
            data=data,
            files=files,
            timeout=300,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Images edit API failed: {response.status_code} {response.text}")
    payload = response.json()
    b64 = payload.get("data", [{}])[0].get("b64_json")
    if not b64:
        raise RuntimeError(f"Images edit API returned no b64_json: {payload}")
    output_path.write_bytes(base64.b64decode(b64))


def white_to_alpha(path: Path, threshold: int = 245) -> None:
    image = Image.open(path).convert("RGBA")
    arr = np.asarray(image).copy()
    rgb = arr[:, :, :3].astype(np.int16)
    brightness = rgb.mean(axis=2)
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    matte = (brightness >= threshold) & (spread <= 35)
    arr[matte, 3] = 0
    Image.fromarray(arr, "RGBA").save(path)


def largest_size_for(path: Path) -> str:
    image = Image.open(path)
    width, height = image.size
    if width == height:
        return "1024x1024"
    return "1536x1024" if width > height else "1024x1536"


def normalize_to_4k(source: Path, output: Path) -> tuple[int, int]:
    image = Image.open(source).convert("RGBA")
    width, height = image.size
    long_edge = max(width, height)
    if long_edge >= 3840:
        shutil.copy2(source, output)
        return (width, height)
    scale = 3840 / long_edge
    new_size = (round(width * scale), round(height * scale))
    upscaled = image.resize(new_size, Image.Resampling.LANCZOS)
    upscaled.save(output)
    return new_size


def sanitize_layer_name(name: str, index: int) -> str:
    safe = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", name).strip("_")
    return safe[:64] or f"Layer_{index:02d}"


def create_background(path: Path, size: tuple[int, int], color: str) -> None:
    rgb = tuple(int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    Image.new("RGBA", size, (*rgb, 255)).save(path)


def build_manifest(project: Path, analysis: dict[str, Any], background_color: str) -> Path:
    restored = project / "restored" / "restored_4k.png"
    width, height = Image.open(restored).size
    layers = [
        {
            "name": "Background",
            "file": "layer_sources/00_background.png",
            "x": 0,
            "y": 0,
            "fit": "none",
            "remove_background": "none",
        }
    ]
    semantic_layers = sorted(analysis.get("layers", []), key=lambda item: item.get("order", 999))
    idx = 1
    for layer in semantic_layers:
        if str(layer.get("type", "")).lower() == "background":
            continue
        name = str(layer.get("name") or f"Layer {idx:02d}")
        filename = f"{idx:02d}_{sanitize_layer_name(name, idx)}.png"
        if not (project / "layer_sources" / filename).exists():
            idx += 1
            continue
        layers.append(
            {
                "name": name,
                "file": f"layer_sources/{filename}",
                "x": 0,
                "y": 0,
                "fit": "none",
                "remove_background": "none",
            }
        )
        idx += 1

    manifest = {
        "canvas": {
            "width": width,
            "height": height,
            "composite_background": background_color,
        },
        "output": "output.psd",
        "preview": "output.preview.png",
        "save_layers_dir": "psd_full_canvas_layers",
        "zip_layers": "psd_full_canvas_layers.zip",
        "layers": layers,
    }
    path = project / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def alpha_bbox(path: Path) -> tuple[int, int, int, int] | None:
    return Image.open(path).convert("RGBA").getchannel("A").getbbox()


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, "#30343b")
    draw = ImageDraw.Draw(image)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#4a4f59")
    return image.convert("RGBA")


def save_element_review_assets(project: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    cropped_dir = project / "elements_cropped"
    cropped_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []

    semantic_layers = [item for item in analysis.get("layers", []) if str(item.get("type", "")).lower() != "background"]
    for idx, layer in enumerate(semantic_layers, start=1):
        name = str(layer.get("name") or f"Layer {idx:02d}")
        filename = f"{idx:02d}_{sanitize_layer_name(name, idx)}.png"
        source = project / "layer_sources" / filename
        if not source.exists():
            continue
        image = Image.open(source).convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        if not bbox:
            continue
        cropped = image.crop(bbox)
        cropped_path = cropped_dir / filename
        cropped.save(cropped_path)
        items.append(
            {
                "index": idx,
                "name": name,
                "type": str(layer.get("type", "")),
                "full_canvas": str(source),
                "cropped": str(cropped_path),
                "bbox": list(bbox),
            }
        )

    columns = 4
    tile_w, tile_h = 260, 300
    rows = max(1, math.ceil(len(items) / columns)) if items else 1
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), "#15171a")
    draw = ImageDraw.Draw(sheet)
    for pos, item in enumerate(items):
        x = (pos % columns) * tile_w
        y = (pos // columns) * tile_h
        preview = Image.open(item["cropped"]).convert("RGBA")
        preview.thumbnail((tile_w - 36, tile_h - 72), Image.Resampling.LANCZOS)
        bg = checkerboard((tile_w - 20, tile_h - 58), 14)
        px = (bg.width - preview.width) // 2
        py = (bg.height - preview.height) // 2
        bg.alpha_composite(preview, (px, py))
        sheet.paste(bg.convert("RGB"), (x + 10, y + 10))
        label = f"{item['index']:02d} {item['name']}"[:38]
        draw.text((x + 12, y + tile_h - 40), label, fill="#f5f5f5")
        draw.text((x + 12, y + tile_h - 22), str(item["type"])[:38], fill="#b8bdc7")

    contact_sheet = project / "elements_contact_sheet.png"
    sheet.save(contact_sheet)
    review_manifest = project / "elements_review_manifest.json"
    review_manifest.write_text(json.dumps({"elements": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "element_count": len(items),
        "contact_sheet": str(contact_sheet),
        "cropped_dir": str(cropped_dir),
        "review_manifest": str(review_manifest),
    }


def write_validation(project: Path, analysis: dict[str, Any], status: str, errors: list[str], review: dict[str, Any] | None = None) -> None:
    report = {
        "status": status,
        "errors": errors,
        "analysis_layer_count": len(analysis.get("layers", [])),
        "output_psd_exists": (project / "output.psd").exists(),
        "preview_exists": (project / "output.preview.png").exists(),
        "review": review or {},
        "notes": [
            "Layer text is raster image content unless separately reconstructed as editable text.",
            "GPT Image layer extraction can alter details; inspect output.preview.png before production use.",
            "Confirm elements_contact_sheet.png before final PSD assembly when the user requested review before merging.",
        ],
    }
    (project / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct OpenAI image-to-PSD pipeline")
    parser.add_argument("--source", required=True, help="input product/poster/screenshot image")
    parser.add_argument("--slug", required=True, help="project slug")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--image-model", default=os.environ.get("IMAGE2_MODEL", "gpt-image-2"))
    parser.add_argument("--vision-model", default=os.environ.get("IMAGE2_VISION_MODEL", "gpt-5.2"))
    parser.add_argument("--image-size", default="auto", help="auto, 1024x1024, 1024x1536, or 1536x1024")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--background", default="#ffffff")
    parser.add_argument("--max-layers", type=int, default=24)
    parser.add_argument("--skip-4k-normalize", action="store_true")
    parser.add_argument("--extract-only", action="store_true", help="write element PNGs, contact sheet, and manifest, then stop before PSD assembly")
    parser.add_argument("--mock-openai", action="store_true", help="offline self-test mode; does not call OpenAI")
    return parser


def mock_analysis_for(image_path: Path) -> dict[str, Any]:
    width, height = Image.open(image_path).size
    return {
        "canvas": {"width": width, "height": height},
        "summary": "Mock semantic analysis for offline pipeline verification.",
        "layers": [
            {
                "name": "Text - Header",
                "type": "title_text",
                "bbox": [0, 0, int(width * 0.45), int(height * 0.25)],
                "order": 1,
                "editable_text_candidate": False,
                "text": "",
                "extraction_prompt": "Extract the header/text area only.",
            },
            {
                "name": "Subject - Main Object",
                "type": "subject",
                "bbox": [int(width * 0.2), int(height * 0.25), int(width * 0.85), int(height * 0.95)],
                "order": 2,
                "editable_text_candidate": False,
                "text": "",
                "extraction_prompt": "Extract the main subject/object only.",
            },
            {
                "name": "Icons - Side Information",
                "type": "icon",
                "bbox": [0, int(height * 0.4), int(width * 0.2), int(height * 0.9)],
                "order": 3,
                "editable_text_candidate": False,
                "text": "",
                "extraction_prompt": "Extract side icons or information elements only.",
            },
        ],
    }


def mock_layer_from_bbox(source: Path, output: Path, bbox: list[int]) -> None:
    image = Image.open(source).convert("RGBA")
    width, height = image.size
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if x2 > x1 and y2 > y1:
        layer.alpha_composite(image.crop((x1, y1, x2, y2)), dest=(x1, y1))
    else:
        draw = ImageDraw.Draw(layer)
        draw.rectangle((0, 0, width // 4, height // 4), fill=(255, 0, 0, 160))
    layer.save(output)


def main() -> int:
    args = build_parser().parse_args()
    api_key = "mock" if args.mock_openai else require_api_key()
    if not args.mock_openai:
        require_base_url()
    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")
    image2psd_script = resolve_image2psd_script()

    project = unique_project_dir(args.date, slugify(args.slug))
    for subdir in ["original", "restored", "analysis", "layer_sources", "psd_full_canvas_layers", "diagnostics"]:
        (project / subdir).mkdir(parents=True, exist_ok=True)
    original = project / "original" / "input.png"
    ImageOps.exif_transpose(Image.open(source)).convert("RGBA").save(original)

    size = largest_size_for(original) if args.image_size == "auto" else args.image_size
    restored_image2 = project / "restored" / "restored_image2.png"
    restored_4k = project / "restored" / "restored_4k.png"
    native_layers_dir = project / "diagnostics" / "native_layer_sources"
    native_layers_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    if args.mock_openai:
        shutil.copy2(original, restored_image2)
    else:
        call_image_edit(
            api_key,
            args.image_model,
            original,
            RESTORE_PROMPT,
            restored_image2,
            size=size,
            transparent=False,
            quality=args.quality,
        )
    if args.skip_4k_normalize:
        shutil.copy2(restored_image2, restored_4k)
    else:
        normalize_to_4k(restored_image2, restored_4k)

    analysis = mock_analysis_for(restored_image2) if args.mock_openai else call_responses_analysis(api_key, args.vision_model, restored_image2)
    analysis_layers = analysis.get("layers", [])
    if not isinstance(analysis_layers, list) or not analysis_layers:
        raise RuntimeError("analysis produced no layers")
    analysis["layers"] = sorted(analysis_layers, key=lambda item: item.get("order", 999))[: args.max_layers]
    (project / "analysis" / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    width, height = Image.open(restored_4k).size
    create_background(project / "layer_sources" / "00_background.png", (width, height), args.background)

    semantic_layers = [item for item in analysis["layers"] if str(item.get("type", "")).lower() != "background"]
    for idx, layer in enumerate(semantic_layers, start=1):
        name = str(layer.get("name") or f"Layer {idx:02d}")
        filename = f"{idx:02d}_{sanitize_layer_name(name, idx)}.png"
        prompt = str(layer.get("extraction_prompt") or "").strip()
        if not prompt:
            prompt = f"Extract only the semantic element named {name}."
        layer_prompt = f"""Create a transparent PNG layer for PSD assembly.
Input is the restored full poster image. Extract only: {name}.

Element-specific instruction:
{prompt}

Requirements:
- keep the same canvas size and aspect ratio;
- keep the element at its original position;
- make every other pixel transparent;
- do not move, resize, stretch, crop, rotate, or redesign the element;
- preserve original text exactly when the element contains text;
- no white background, no gray matte, no fake transparency, no dirty edges;
- output PNG with transparency."""
        try:
            native_layer_path = native_layers_dir / filename
            final_layer_path = project / "layer_sources" / filename
            if args.mock_openai:
                mock_layer_from_bbox(restored_image2, native_layer_path, layer.get("bbox", []))
            else:
                try:
                    call_image_edit(
                        api_key,
                        args.image_model,
                        restored_image2,
                        layer_prompt,
                        native_layer_path,
                        size=size,
                        transparent=True,
                        quality=args.quality,
                    )
                except Exception as exc:
                    if "Transparent background is not supported" not in str(exc):
                        raise
                    fallback_prompt = layer_prompt + "\nIf transparency is not available, use a pure white background outside the extracted element."
                    call_image_edit(
                        api_key,
                        args.image_model,
                        restored_image2,
                        fallback_prompt,
                        native_layer_path,
                        size=size,
                        transparent=False,
                        quality=args.quality,
                    )
                    white_to_alpha(native_layer_path)
            if args.skip_4k_normalize:
                shutil.copy2(native_layer_path, final_layer_path)
            else:
                normalize_to_4k(native_layer_path, final_layer_path)
        except Exception as exc:
            errors.append(f"layer {idx} {name}: {exc}")

    manifest = build_manifest(project, analysis, args.background)
    review = save_element_review_assets(project, analysis)
    if args.extract_only:
        status = "awaiting_confirmation" if not errors else "partial_awaiting_confirmation"
        write_validation(project, analysis, status, errors, review)
        psd_status = "not_assembled_extract_only"
    else:
        subprocess.run([sys.executable, str(image2psd_script), "assemble", "--manifest", str(manifest)], check=True)
        status = "ok" if not errors else "partial"
        write_validation(project, analysis, status, errors, review)
        psd_status = "assembled"
    (project / "process_notes.md").write_text(
        "\n".join(
            [
                "# Process Notes",
                "",
                "Pipeline: OpenAI image restoration -> OpenAI semantic analysis -> OpenAI transparent layer generation -> PSD assembly.",
                f"Image model: `{args.image_model}`",
                f"Vision model: `{args.vision_model}`",
                f"Image API size: `{size}`",
                f"PSD assembly: `{psd_status}`",
                "",
                "Inspect `elements_contact_sheet.png`, `validation_report.json`, and `output.preview.png` when present before production use.",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "project_dir": str(project),
                "status": status,
                "manifest": str(manifest),
                "contact_sheet": review.get("contact_sheet"),
                "psd": str(project / "output.psd") if (project / "output.psd").exists() else None,
                "preview": str(project / "output.preview.png") if (project / "output.preview.png").exists() else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
