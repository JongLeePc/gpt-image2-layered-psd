# API And Prompting Notes

## Source Article Summary

The referenced WeChat image article is an example of the desired decomposition workflow:

1. Start from a source design image.
2. Use structured instructions so the model can follow the user's decomposition requirements.
3. Use a "Thinking" decomposition step to split important elements into organized layer groups.
4. Export/download a PSD and open it in Photoshop with layer order and groups in place.

The practical takeaway is not a new official PSD response parameter. Treat "Thinking" as a planning and decomposition prompt pattern: ask the downstream layerizer to identify background, subject, text, badges, icons, decorations, foreground objects, and shadows from the uploaded image.

## Official-Compatible Images API Shape

Use:

```http
POST <base_url>/images/generations
Authorization: Bearer <api_key>
Content-Type: application/json
```

Typical body:

```json
{
  "model": "gpt-image-2",
  "prompt": "A complete design prompt...",
  "size": "1024x1536",
  "quality": "high",
  "output_format": "png"
}
```

Use `png` for PSD workflows because it preserves image quality and can support transparency in related edit steps. Use `jpeg` or `webp` only when smaller files matter more than layer extraction quality.

## Prompt Strategy

Include these clauses when generating or extracting layers:

- Keep background, main subject, title text, badges, icons, decorations, and shadows visually separable.
- Preserve exact requested text.
- Avoid tiny text, merged UI mockups, screenshots of Photoshop, and fake layer panels.
- Use a clean canvas and predictable hierarchy.

For single complete element extraction, use wording like:

```text
Create a complete standalone cutout of the target object.
The source image shows the object partially occluded; reconstruct the hidden/missing portions naturally.
Preserve the target object's material, perspective, lighting, color, texture, and visible markings.
Remove all background, pedestal, neighboring objects, shadows, and unrelated content.
Place only the completed object on a perfectly flat solid chroma-key background for background removal.
No checkerboard, no cast shadow, no watermark, no labels outside the object.
```

If the target must remain pixel-faithful to the original visible area, state that separately and only reconstruct the hidden parts.

## Chroma Key Selection

Do not use a universal green-screen background. Pick a key color that does not appear in the subject:

- Use `#00ff00` only when the subject has no green areas.
- Use `#ff00ff` for green subjects, green products, green leaves, plants, tanks, or green accessories.
- Use a cyan or blue key only when the subject has no cyan/blue areas.
- After removing the key, inspect whether small colored details disappeared. If they did, redo the element with a safer key color.

For elements that must preserve original pixels exactly, prefer mask-based cutout over chroma-key removal. For hidden/occluded elements, use AI completion first, then remove a non-conflicting solid background.

## API Key Handling

Read keys from environment variables only:

1. `GPT_IMAGE2_API_KEY`
2. `OPENAI_API_KEY`

Never write keys into generated manifests, notes, screenshots, examples, or SKILL.md.
