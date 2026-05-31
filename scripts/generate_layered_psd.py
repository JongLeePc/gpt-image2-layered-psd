#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import requests
from PIL import Image, ImageDraw


SKILL_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = SKILL_ROOT / "projects"
DOWNSTREAM_ROOT = Path.home() / ".codex" / "skills" / "image2-ai-psd-layerizer"
DOWNSTREAM_SCRIPT = DOWNSTREAM_ROOT / "scripts" / "run_image2_psd.py"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "gpt_image2_layered_psd"


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


def read_api_key(args: argparse.Namespace) -> str:
    key = args.api_key or os.environ.get("GPT_IMAGE2_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit(
            "Missing API key. Set GPT_IMAGE2_API_KEY or OPENAI_API_KEY before running, "
            "or use --mock-openai for an offline structural test."
        )
    return key


def read_design_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.prompt_json:
        path = Path(args.prompt_json).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"prompt JSON not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit("prompt JSON must contain an object at the top level")
        return data
    if args.prompt:
        return {
            "request": args.prompt,
            "layering": [
                "Design for later semantic PSD decomposition.",
                "Keep background, main subject, titles, badges, icons, decorations, and shadows visually separable.",
            ],
        }
    raise SystemExit("Provide either --prompt-json or --prompt")


def build_generation_prompt(design: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Create a polished production-ready design image from this JSON design brief.",
            "Think through the composition internally before rendering.",
            "Design for downstream PSD decomposition: keep background, main subject, title text, badges, icons, decorative elements, shadows, and foreground props visually separable.",
            "Preserve requested text exactly. Prefer short, large, high-contrast typography. Avoid fake Photoshop UI, layer panels, watermarks, or process diagrams.",
            "Return only the final artwork image.",
            "",
            "JSON design brief:",
            json.dumps(design, ensure_ascii=False, indent=2),
        ]
    )


def call_image_generation(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    size: str,
    quality: str,
    output_format: str,
    output_path: Path,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "output_format": output_format,
    }
    response = requests.post(
        f"{base_url.rstrip('/')}/images/generations",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=300,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Images generation API failed: {response.status_code} {response.text}")
    payload = response.json()
    item = (payload.get("data") or [{}])[0]
    if item.get("b64_json"):
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        request = Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=180) as remote:
            output_path.write_bytes(remote.read())
    else:
        raise RuntimeError(f"Images generation response contained no b64_json or url: {payload}")
    return {"request": body, "response_keys": sorted(payload.keys())}


def create_mock_image(output_path: Path, design: dict[str, Any], size: str) -> None:
    width, height = parse_size(size)
    image = Image.new("RGB", (width, height), "#f7fbff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, int(height * 0.38)), fill="#007AFF")
    draw.rectangle((int(width * 0.08), int(height * 0.48), int(width * 0.92), int(height * 0.88)), outline="#1C1C1E", width=max(4, width // 180))
    draw.ellipse((int(width * 0.62), int(height * 0.52), int(width * 0.82), int(height * 0.66)), fill="#FFCC00")
    title = "GPT-Image2 PSD Mock"
    if "text" in design and isinstance(design["text"], list) and design["text"]:
        first = design["text"][0]
        if isinstance(first, dict) and first.get("content"):
            title = str(first["content"])
    draw.text((int(width * 0.08), int(height * 0.12)), title[:40], fill="white")
    draw.text((int(width * 0.12), int(height * 0.55)), "Subject / Product", fill="#1C1C1E")
    draw.text((int(width * 0.12), int(height * 0.76)), "Badge / CTA / Icons", fill="#1C1C1E")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def parse_size(size: str) -> tuple[int, int]:
    if size == "auto":
        return 1024, 1536
    match = re.fullmatch(r"(\d+)x(\d+)", size)
    if not match:
        raise SystemExit(f"Unsupported size for mock image: {size}")
    return int(match.group(1)), int(match.group(2))


def prepare_source_image(source_path: Path, project: Path) -> Path:
    if not source_path.exists():
        raise SystemExit(f"source image not found: {source_path}")
    input_dir = project / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / "source.png"
    Image.open(source_path).convert("RGBA").save(target)
    return target


def run_downstream_layerizer(args: argparse.Namespace, project: Path, source: Path, env: dict[str, str]) -> dict[str, Any]:
    if not DOWNSTREAM_SCRIPT.exists():
        raise SystemExit(f"Downstream layerizer not found: {DOWNSTREAM_SCRIPT}")
    cmd = [
        sys.executable,
        str(DOWNSTREAM_SCRIPT),
        "--source",
        str(source),
        "--slug",
        f"{project.name}_from_generation",
        "--image-model",
        args.model,
        "--image-size",
        args.size,
        "--quality",
        args.quality,
        "--max-layers",
        str(args.max_layers),
    ]
    if args.mock_openai:
        cmd.append("--mock-openai")
        cmd.append("--skip-4k-normalize")
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    objects = parse_json_objects(completed.stdout)
    if objects:
        return {
            "layerizer_result": objects[-1],
            "emitted_json_count": len(objects),
            "stderr": completed.stderr.strip(),
        }
    return {"stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def parse_json_objects(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        objects.append(obj)
        idx = start + end
    return objects


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a source image and assemble it into separated element PNGs plus a layered PSD project.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", help="uploaded/local image to analyze and split into layers")
    group.add_argument("--prompt-json", help="JSON design requirements file")
    group.add_argument("--prompt", help="optional plain text prompt for generating a new source image first")
    parser.add_argument("--slug", required=True, help="project slug")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--base-url", default=os.environ.get("GPT_IMAGE2_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=None, help="API key override; prefer environment variables to avoid shell history leaks")
    parser.add_argument("--model", default=os.environ.get("GPT_IMAGE2_MODEL", DEFAULT_MODEL))
    parser.add_argument("--size", default="1024x1536")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--output-format", default="png", choices=["png", "jpeg", "webp"])
    parser.add_argument("--max-layers", type=int, default=12)
    parser.add_argument("--mock-openai", action="store_true", help="offline structural test; does not call APIs")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project = unique_project_dir(args.date, slugify(args.slug))
    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = args.base_url.rstrip("/")
    env["IMAGE2_MODEL"] = args.model

    if args.source:
        source = prepare_source_image(Path(args.source).expanduser().resolve(), project)
        generation_meta = {"source_mode": "uploaded_image", "mock_openai": args.mock_openai}
        if not args.mock_openai:
            env["OPENAI_API_KEY"] = read_api_key(args)
    else:
        design = read_design_request(args)
        generated_dir = project / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        source = generated_dir / f"source.{args.output_format}"
        prompt = build_generation_prompt(design)
        (project / "design_request.json").write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
        (project / "generation_prompt.txt").write_text(prompt, encoding="utf-8")

        if args.mock_openai:
            create_mock_image(source, design, args.size)
            generation_meta = {"source_mode": "generated_image", "mock_openai": True}
        else:
            api_key = read_api_key(args)
            env["OPENAI_API_KEY"] = api_key
            generation_meta = call_image_generation(
                api_key=api_key,
                base_url=args.base_url,
                model=args.model,
                prompt=prompt,
                size=args.size,
                quality=args.quality,
                output_format=args.output_format,
                output_path=source,
            )

        if args.output_format != "png":
            png_source = generated_dir / "source.png"
            Image.open(source).convert("RGBA").save(png_source)
            source = png_source

    downstream = run_downstream_layerizer(args, project, source, env)
    notes = {
        "generated_project": str(project),
        "generated_source": str(source),
        "generation_meta": generation_meta,
        "downstream": downstream,
    }
    (project / "process_notes.md").write_text(
        "\n".join(
            [
                "# Process Notes",
                "",
                "Pipeline: source image -> semantic PSD layerizer -> separated element PNGs -> PSD assembly.",
                f"Base URL: `{args.base_url.rstrip('/')}`",
                f"Image model: `{args.model}`",
                f"Size: `{args.size}`",
                f"Quality: `{args.quality}`",
                "",
                "API keys are intentionally not written to this file.",
                "Inspect the downstream `validation_report.json` and `output.preview.png` before production use.",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(notes, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
