# UI Assets

`src/slf_trace/ui/assets/` holds static branding and visual assets for user-facing UIs.

Current use:

- `SLF-logo-bg-white.svg` is the company logo used in Panel headers.

Rules:

- Put user-facing branding assets here instead of duplicating them in feature modules.
- Load assets through `importlib.resources`, not hard-coded filesystem paths.
- Keep names stable when assets are referenced from UI code or docs.

When adding a new user-facing UI, prefer reusing assets from this folder so the brand stays
consistent across operator, supervisor, and admin surfaces.
