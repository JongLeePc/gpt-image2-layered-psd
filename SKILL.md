---
name: gpt-image2-layered-psd
description: Analyze uploaded or existing images and convert them into separated element PNGs and editable layered PSD projects using GPT-Image2 through an OpenAI-compatible third-party Images API. Use when Codex needs to take a poster, product image, ecommerce graphic, social-media image, screenshot, cover, or flat design draft and produce semantic layers, Photoshop-ready PSD, layer PNGs, manifest files, and previews.
---

# GPT-Image2 Layered PSD

Use this skill for the workflow described as "image analysis + Thinking decomposition + element separation + PSD export": start from the user's uploaded image or an existing local image, analyze the visual elements, generate separate transparent element PNGs, then assemble a Photoshop-editable PSD project.

For occluded product elements, do not stop at visible-pixel cutout. Produce a complete reconstructed element when the user expects a standalone asset.

## Quick Start

Confirm one element first before batch splitting:

1. Ask or infer the target element, for example "white PLA filament spool".
2. Extract/generate only that element.
3. If part of the element is hidden by another object, reconstruct the missing part so the element is complete.
4. Show the transparent PNG preview and wait for confirmation before batch processing.

Primary workflow for an uploaded/local image:

```bash
python ~/.codex/skills/gpt-image2-layered-psd/scripts/generate_layered_psd.py \
  --source /path/to/input.png \
  --slug summer_poster
```

Optional generation workflow only when the user explicitly asks to create a new source image first:

```bash
python ~/.codex/skills/gpt-image2-layered-psd/scripts/generate_layered_psd.py \
  --prompt "Create a vertical summer ecommerce poster with headline, beach product scene, offer badge, and clean layerable composition." \
  --slug summer_poster
```

Offline structural self-test:

```bash
python ~/.codex/skills/gpt-image2-layered-psd/scripts/generate_layered_psd.py \
  --prompt "mock poster" \
  --slug smoke_test \
  --mock-openai
```

## Required Backend

Default API base URL: `https://api.openai.com/v1`.

For OpenAI-compatible third-party image gateways, set `GPT_IMAGE2_BASE_URL`
or pass `--base-url`.

Default image model: `gpt-image-2`.

Read the API key from `GPT_IMAGE2_API_KEY` first, then `OPENAI_API_KEY`. Do not hardcode API keys into skill files, prompts, manifests, or logs.

The script uses the OpenAI-compatible image generation format:

```json
{
  "model": "gpt-image-2",
  "prompt": "...",
  "size": "1024x1536",
  "quality": "high",
  "output_format": "png"
}
```

Endpoint: `<base_url>/images/generations`.

## Workflow

1. Locate the user-uploaded image or ask for the image path only if no image is available.
2. Start with one target element confirmation when quality matters.
3. Decide extraction mode per element:
   - **Visible cutout**: preserve only pixels actually visible in the source image.
   - **Complete element**: reconstruct hidden/occluded portions so the element becomes a standalone usable asset.
4. Run semantic PSD decomposition using `image2-ai-psd-layerizer` only after the single-element direction is accepted.
5. Generate transparent element PNGs for background, subject, text, badges, icons, decorations, shadows, and foreground objects where possible.
6. Show a contact sheet and the element PNG directory to the user for review.
7. Wait for explicit user confirmation that all elements are correct before assembling the PSD.
8. Assemble the PSD and preview only after confirmation.
9. Inspect the preview and validation report before claiming production readiness.

## Confirmed Single-Element PSD Workflow

Use this workflow when the user wants "single elements", "complete elements",
"not chunks", "not cut into blocks", or "elements must be separate".

1. Build a **confirmed element library** first:
   - Text and icon elements may be source-fidelity transparent layers.
   - Photo cards, material swatches, labels, dimension marks, arrows, products,
     props, shadows, and platforms should each be one semantic element.
   - Occluded/cut-off products should be reconstructed into complete standalone
     transparent PNGs when the user asks for complete elements.
2. Show a contact sheet of the element library and wait for confirmation.
3. Do not use loose `visible_*_source` object masks as final single-element
   product layers. Those are only acceptable for an **original-visible layout**
   candidate, not for a final "single element" PSD.
4. When assembling PSD after confirmation:
   - Put the background at the bottom.
   - Put shadows and structural supports below products.
   - Place one semantic object per PSD layer.
   - Keep repaired complete products as product layers only when their placement
     has been checked; otherwise keep them as separate asset PNGs.
5. Self-check before showing the PSD:
   - Inspect each product/object layer on a dark background to catch white matte,
     transparent holes, color-key damage, or accidental neighboring objects.
   - Inspect the flattened preview against the source layout.
   - Verify the PSD layer stack opens with the background below all objects.
   - If the candidate is wrong, delete it before showing the user.

Two valid PSD modes exist; do not mix them without saying so:

- **Original-visible layout PSD**: uses source-visible layers so the flattened
  preview matches the uploaded image. These layers may include only visible
  portions of occluded objects and are not standalone complete assets.
- **Single-complete-elements PSD**: uses repaired/complete standalone elements.
  This satisfies independent element editing, but the flattened preview may
  differ from the source where the source had occlusion or cropping.

## Complete Element Extraction

Use complete extraction when the user says the element is "not complete", "missing bottom", "hidden", "blocked", "occluded", or needs to be usable as an independent product cutout.

Process:

1. Use source image analysis to identify the target and visible region.
2. Generate or edit a standalone version of the target element on a flat chroma-key background.
3. Reconstruct occluded or cropped areas consistently with the object's geometry, material, lighting, perspective, and markings.
4. Remove the chroma-key background locally into alpha.
5. Save a cropped transparent PNG for user confirmation.

Chroma-key rule:

- Never use one fixed key color for every element.
- Choose a key color that is absent from the subject.
- Do not use green (`#00ff00`) for green subjects or subjects with green details.
- Use magenta (`#ff00ff`) for green elements such as leaves or green products unless the subject itself contains magenta.
- Inspect the alpha result; if key removal changes subject colors or deletes details, regenerate with a non-conflicting key color or use a mask-based cutout.

Prompt constraints for completion:

- Preserve the target object's identity, material, perspective, lighting, and visible markings.
- Reconstruct missing parts naturally; do not leave pedestal, background, neighboring objects, shadows, or cut-off edges.
- Use a flat solid chroma-key background for local alpha removal.
- Do not include checkerboard backgrounds, Photoshop UI, labels outside the object, or watermarks.

The script creates a project under:

```text
~/.codex/skills/gpt-image2-layered-psd/projects/YYYYMMDD_slug/
  input/source.png
  process_notes.md
```

It then delegates PSD layer extraction and assembly to:

```text
~/.codex/skills/image2-ai-psd-layerizer/projects/YYYYMMDD_slug_from_generation/
  output.psd
  output.preview.png
  manifest.json
  validation_report.json
  layer_sources/
  psd_full_canvas_layers.zip
```

## Optional JSON Requirement Pattern

Only use JSON instructions when generating a new source image or when the user gives explicit decomposition preferences. For uploaded images, treat the image as the source of truth:

```json
{
  "canvas": {
    "orientation": "vertical",
    "size": "1024x1536",
    "background": "transparent-friendly layered design"
  },
  "subject": "main product or scene",
  "text": [
    {"role": "headline", "content": "Exact headline text"},
    {"role": "subtitle", "content": "Exact subtitle text"},
    {"role": "badge", "content": "Offer badge text"}
  ],
  "style": {
    "palette": ["#007AFF", "#1C1C1E", "#FFFFFF"],
    "mood": "clean, premium, ecommerce-ready"
  },
  "layering": [
    "separate background, main subject, title text, badges, icons, foreground decorations, and shadows",
    "avoid merged text-on-background areas where possible",
    "keep strong visual separation between elements"
  ],
  "constraints": [
    "preserve all requested text exactly",
    "no fake Photoshop UI in the final artwork",
    "design for later PSD decomposition"
  ]
}
```

## Quality Rules

- Start from the uploaded image when one is provided. Do not replace it with a newly generated image unless the user explicitly asks for redesign/regeneration.
- Do not claim the image API itself returns native PSD unless the actual response contains a PSD file. This skill creates PSD through post-processing and PSD assembly.
- Treat text layers as raster layer candidates unless a downstream process reconstructs editable Photoshop text separately.
- Do not present an occluded visible-pixel cutout as a complete standalone element. If the source hides part of an element, either reconstruct it or label the output as visible-only.
- Do not assemble the final PSD immediately after extraction. Always stop at the contact-sheet/element-review stage and ask for confirmation first.
- After PSD assembly, show the preview and treat the PSD as a candidate until the user accepts it. If the user says the generated file is not the desired result, delete that candidate PSD, preview, manifest, saved layer PNGs, and zip outputs automatically; keep only previously confirmed source elements.
- Do not make the user repeatedly review unverified candidates. Before showing a PSD candidate, inspect the single layers and the composite yourself. If it fails the user's stated criteria, delete it and continue improving it.
- Do not include duplicate semantic elements in the final set. For each object choose one final layer: source-faithful visible cutout, repaired complete element, or reconstructed clean element.
- When assembling PSD files for Photoshop, ensure the background layer is written and displayed at the bottom of the layer stack. Opening the PSD must not show a white/background layer covering all other layers.
- If exact text fidelity matters, keep text short, large, and high contrast, then verify `output.preview.png`.
- Keep decomposition honest: report merged areas, uncertain text, missing transparency, or element changes from `validation_report.json`.
- If transparent layer extraction fails or changes content, report the limitation from `validation_report.json`.

## References

Read `references/api-and-prompting.md` when adjusting parameters, adding provider-specific fields, or refining the JSON prompt strategy.
