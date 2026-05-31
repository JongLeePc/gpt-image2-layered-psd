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

Install Python dependencies on the target device:

```powershell
python -m pip install -r .\scripts\requirements.txt
```

The skill bundles its own semantic layerizer and PSD writer:

```text
scripts/generate_layered_psd.py
scripts/run_image2_psd.py
scripts/image2psd.py
```

It does not require the private/local `image2-ai-psd-layerizer` or `bggg-creator-image2psd` skills on another device.

## Required API Configuration

On a new device, configure the third-party OpenAI-compatible gateway before running real extraction:

```powershell
$env:GPT_IMAGE2_API_KEY = "sk-..."
$env:GPT_IMAGE2_BASE_URL = "https://your-openai-compatible-host/v1"
$env:GPT_IMAGE2_MODEL = "gpt-image-2"
```

`OPENAI_API_KEY` and `OPENAI_BASE_URL` are also supported as fallbacks, but `GPT_IMAGE2_*` is preferred so the configuration is explicit for this skill.

Do not commit API keys into this repository, prompts, manifests, logs, screenshots, or examples.

If the API key is missing, the script exits with a clear message asking for `GPT_IMAGE2_API_KEY` or `OPENAI_API_KEY`. If the base URL is missing, the skill instructions tell Codex to ask the user for the third-party base URL before a real run.

Optional advanced overrides:

```powershell
$env:GPT_IMAGE2_DOWNSTREAM_SCRIPT = "C:\path\to\custom\run_image2_psd.py"
$env:GPT_IMAGE2_PSD_WRITER = "C:\path\to\custom\image2psd.py"
```

## Usage

From the skill directory:

```powershell
python .\scripts\generate_layered_psd.py `
  --source C:\path\to\poster.png `
  --slug poster_layer_test `
  --max-layers 16
```

Extract elements and stop for confirmation before PSD assembly:

```powershell
python .\scripts\generate_layered_psd.py `
  --source C:\path\to\poster.png `
  --slug poster_layer_test `
  --max-layers 24 `
  --extract-only
```

Offline structural smoke test:

```powershell
python .\scripts\generate_layered_psd.py `
  --prompt "mock poster" `
  --slug smoke_test `
  --mock-openai
```

Prepare only a standalone handoff project:

```powershell
python .\scripts\generate_layered_psd.py `
  --source C:\path\to\poster.png `
  --slug poster_layer_test `
  --skip-downstream
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
