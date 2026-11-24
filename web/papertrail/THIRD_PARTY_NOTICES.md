# Papertrail browser components

These are local, pinned browser assets. No package lifecycle scripts, remote model code, shared Python upgrades, external font or CDN requests are required to run the workbench.

- **Preact11.1.0**, MIT, Jason Miller and contributors. Native component rendering, virtual DOM and hooks execute directly from the unmodified npm distributions `dist/vendor/preact.mjs` and `hooks.mjs`; the full license is retained as `PREACT_LICENSE`. Official registry archive integrity and local asset SHA256 values are in `reports/stage23/assets-lock.json`. Reviewed GitHub version-tag package and native DOM diff/props sources are in `upstream-audit.json`.
- **HTM3.1.1**, Apache-2.0, copyright2018 Google Inc. Native tagged templates call Preact; no custom JSX/parser or training framework is substituted. The unmodified browser distribution is `htm.mjs`, with full `HTM_LICENSE`. Archive integrity is pinned; the package archive contained LICENSE and no separate NOTICE file. Source references and scope are recorded in the same audit.
- **Lucide1.8.0**, ISC plus retained Feather-derived copyright/license text. Selected native icon node arrays were exported from the Codex bundled package without changing path data. `icons.json`, full `LUCIDE_LICENSE`, selected names and file hashes are recorded in `icons-lock.json`. The review is bounded, not an assertion of complete dependency vulnerability certification.

Compared but not installed or copied: **assistant-ui**, MIT, active repository at review, whose React/radix/store/runtime integration would add adaptation/dependency cost for the fixed HTTP policy; **Chainlit**, Apache-2.0, repository archived at review. README/license/package sources and the unavailable guessed assistant-ui runtime source path are explicitly distinguished in the audit. No source was inferred from an unread file.

Application-specific code implements layout, typed request projection, streaming presentation, local history and allowed-ID source sessions. Algorithms, BM25, SAR/TF-IDF, original parsing and the fixed policy are existing project components with their earlier notices. Codex is a layout reference; this website is the project's Papertrail interface.

Personal feedback, cached original responses and user-derived traces stay in ignored data/.cache. User selected local interactive delivery now, online sharing later. This phase does not create a cloud Site, upload personal assets, or alter the audience of any hosted site.
