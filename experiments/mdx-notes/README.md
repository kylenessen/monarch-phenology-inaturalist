---
author: Codex
---

# MDX note experiment

This is a tested prototype for placing the existing monarch weather figure inside narrative prose with note-owned controls. It accompanies the November 14, 2026 discussion note in the Notes vault. The authoritative analysis and observation archive remain in this repository.

## Run locally

From the repository root, install the locked JavaScript dependencies and build the note.

```sh
npm ci --prefix experiments/mdx-notes
npm run build --prefix experiments/mdx-notes
```

Serve the built note and the existing weather lab in separate terminals.

```sh
uv run python -m http.server 8771 --bind 127.0.0.1 --directory experiments/mdx-notes/dist
uv run python -m http.server 8769 --bind 127.0.0.1 --directory runs/weather-pilot
```

Open http://127.0.0.1:8771/. The source is `MonarchNote.mdx`. `WeatherLab.jsx` supplies React state for stage, units, and figure visibility. Changes to stage or units reload the embedded figure with validated URL parameters. There is no cross-frame message protocol and no separate density implementation. The lab supports `?embed=plot&stage=pupa&units=C#overnight`. A bare `?embed=plot#overnight` opens the full retained selection with the existing default units.

The build compiles the trusted local MDX file and bundles React locally with esbuild. No CDN is required to view the built page. `node_modules` and `dist` are ignored. `package-lock.json` records exact installed dependencies. Rebuild after editing the MDX source. The experiment does not watch or compile arbitrary vault files, install an Obsidian plugin, or publish data to a web host.

## Use from a normal Obsidian note

A literal iframe in a Markdown note can show the existing figure directly.

```html
<iframe src="http://127.0.0.1:8769/?embed=plot#overnight" title="Monarch weather density" width="100%" height="740"></iframe>
```

To show the MDX note, use `http://127.0.0.1:8771/` as the iframe source. Read mode renders the iframe. A synchronized note on another device needs its own reachable server. A localhost URL points to the device displaying the note. The saved static figure in the vault provides an offline reading copy.

## Findings

An iframe is enough to interact with the existing figure inside Obsidian. MDX adds a document authoring layer for imported components, React state and controls placed among paragraphs. The proof here is a real MDX build and a working imported component, not native Obsidian support for `.mdx` files. The current Notes vault has no MDX renderer enabled. Renaming its notes to `.mdx` would not provide this runtime.

For a larger system, keep the vault's Markdown discussion notes canonical. Store trusted components and build configuration in the project repository. Compile a deliberately selected set of authored MDX documents, serve their bundles, and embed them in ordinary notes. Record the dataset snapshot and relevant initial settings with each figure. Build or render untrusted downloaded MDX only after review because MDX can contain executable code. A hosted version, a desktop bridge, live editing and persisted analysis state are separate work from this experiment.

Sources are the official [MDX format explanation](https://mdxjs.com/docs/what-is-mdx/), [MDX compilation and components guide](https://mdxjs.com/docs/using-mdx/), [compiler reference](https://mdxjs.com/packages/mdx/), [Obsidian web embeds](https://obsidian.md/help/Editing+and+formatting/Embed+web+pages), and [Obsidian HTML behavior](https://obsidian.md/help/html).
