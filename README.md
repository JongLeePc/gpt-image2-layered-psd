# GPT-Image2 Layered PSD Skill

Codex skill for converting a flat design image into confirmed single-element PNGs and Photoshop-ready layered PSD projects.

The workflow is optimized for product posters, ecommerce images, social-media graphics, and design drafts where the user needs independent elements rather than rectangular image chunks.

## What It Does

- Analyzes an uploaded/local source image.
- Extracts semantic visual elements such as text, icons, photo cards, products, dimension marks, platforms, and shadows.
- Supports complete standalone product cutouts when an object is occluded or partially hidden.
- Produces transparent PNG element libraries, cropped element previews, contact sheets, manifests, and candidate PSDs.
- Enforces a confirmation step before final PSD assembly.
- Deletes rejected PSD candidates so stale incorrect outputs do not get mixed into the final deliverables.

## Key Workflow Rules

- Confirm elements before building the final PSD.
- Do not use loose source-visible object masks as final "single element" product layers.
- Treat PSD outputs as candidates until the user accepts the preview.
- Inspect object layers on a dark background before showing a candidate.
- Keep the PSD background layer at the bottom of the stack.
- Keep API keys in environment variables only.

## Requirements

- Python 3.10+
- Pillow
- requests
- Optional: OpenCV / NumPy for local mask cleanup workflows
- Codex skill runtime
- A PSD assembly helper compatible with `bggg-creator-image2psd/scripts/image2psd.py`

The bundled script delegates heavy semantic decomposition to a downstream local skill when available:

```text
~/.codex/skills/image2-ai-psd-layerizer/scripts/run_image2_psd.py
```

If that downstream skill is not installed, the instructions in `SKILL.md` can still be used as the workflow contract, but the included CLI will stop before decomposition.

## Configuration

Use environment variables:

```powershell
$env:GPT_IMAGE2_API_KEY = "..."
$env:GPT_IMAGE2_BASE_URL = "https://api.openai.com/v1"
$env:GPT_IMAGE2_MODEL = "gpt-image-2"
```

`OPENAI_API_KEY` and `OPENAI_BASE_URL` are also supported as fallbacks.

Do not commit API keys into this repository, prompts, manifests, logs, screenshots, or examples.

## Usage

From the skill directory:

```powershell
python .\scripts\generate_layered_psd.py `
  --source C:\path\to\poster.png `
  --slug poster_layer_test `
  --max-layers 16
```

Offline structural smoke test:

```powershell
python .\scripts\generate_layered_psd.py `
  --prompt "mock poster" `
  --slug smoke_test `
  --mock-openai
```

## Output

Projects are created under:

```text
projects/YYYYMMDD_slug/
```

Generated project folders are intentionally ignored by Git.

Typical reviewed outputs include:

- `elements_alpha/` transparent full-canvas layers
- `elements_cropped/` cropped single-element previews
- contact sheet PNG
- PSD candidate
- PSD preview PNG
- manifest JSON
- saved full-canvas layer PNGs
- zipped layer PNGs

## License

MIT
