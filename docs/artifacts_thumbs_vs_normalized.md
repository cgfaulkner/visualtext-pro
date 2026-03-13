# Thumbs vs Normalized Images

## Definitions

- **Thumbnails (thumbs/):** Review artifacts for DOCX display only. Small preview images (e.g. 200×200). Config key: `paths.thumbnail_folder`. Example: `run_dir/thumbs`, `slide_thumbnails`. **Never** use a thumbnail path as LLaVA input.

- **Normalized images:** LLaVA model input only. Produced under run `crops/` or `paths.temp_folder` (or system temp). Full-size or upscaled to satisfy `llava.min_normalized_width`. Use only normalized paths when calling the LLaVA provider.

## Config keys

| Key | Purpose |
|-----|---------|
| `paths.thumbnail_folder` | Review/DOCX only; never use for LLaVA input |
| `paths.temp_folder` | Allowed for LLaVA temp/converted images |
| `paths.strict_llava_gate` | If `true`, reject thumbnail paths at LLaVA entrypoint; if `false`, convert then proceed (default) |
| `llava.min_normalized_width` | Minimum width (px) for normalized image; logged and enforced when PIL is available (default 512) |
| `llava.require_min_normalized_width` | If `true`, conversion **fails** when PIL (Pillow) is missing; if `false`, conversion proceeds with a warning and metadata flag `normalized_width_enforced=false` (default `false`) |

## Runtime policy

- **Default (`strict_llava_gate: false`):** If a thumbnail path reaches the LLaVA entrypoint, it is converted to a normalized image under `temp_folder` (UUID filename, atomic write) and the provider is called with that path. The provider never receives a thumbnail path.

- **Strict (`strict_llava_gate: true`):** Thumbnail input is rejected; no conversion; no provider call. Use when thumbnails must never be used.

## Conversion lifecycle

Converted images are written under `paths.temp_folder` with names like `llava_norm_<uuid>.png`. They are covered by **existing temp cleanup** (same as other temp files). No separate cleanup step is required.

## Min-normalized-width and PIL

Conversion **guarantees** min-normalized-width (upscale when needed) only when **PIL (Pillow)** is available. When PIL is not installed:

- **`require_min_normalized_width: true` (readability required):** Conversion fails with a clear error: *"PIL (Pillow) is required to enforce min_normalized_width for LLaVA input. Install Pillow or use pre-normalized images under crops/."* No thumbnail is written; the provider is not called.
- **`require_min_normalized_width: false` (default):** Conversion proceeds by writing the thumbnail bytes to a temp PNG (no resize). The system emits an explicit **warning** and sets metadata **`normalized_width_enforced: false`** so logs and manifest indicate that normalized width could not be enforced. Install Pillow for the guarantee.

Always install Pillow in production if you need guaranteed min-normalized-width for converted thumbnails.

## Permissions

If conversion fails with a permission error (read thumbnail or write temp), the gate returns an error outcome and logs a warning. Ensure `temp_folder` is writable and the thumbnail path is readable.
