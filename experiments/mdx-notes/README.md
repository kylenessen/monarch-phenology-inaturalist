---
author: Codex
---

# Interactive monarch note

The MDX viewer contains a looping North America map of human-labeled larvae and chrysalises, followed by two histograms. The map pools all years into a weekly seasonal cycle. H3 resolution is adjustable from 0 through 15. The histograms count each observation's coldest daily minimum and hottest daily maximum over D−7 through D−1. They pool all dates independently of the map's animation.

## Run locally

Build the viewer from the repository root.

```sh
npm ci --prefix experiments/mdx-notes
npm run build --prefix experiments/mdx-notes
```

Serve the viewer and its two figures in separate terminals.

```sh
uv run python -m http.server 8771 --bind 127.0.0.1 --directory experiments/mdx-notes/dist
uv run python -m http.server 8768 --bind 127.0.0.1 --directory runs/phenology-map
uv run python -m http.server 8769 --bind 127.0.0.1 --directory runs/weather-pilot
```

Open http://127.0.0.1:8771/. Rebuild after editing `MonarchNote.mdx`. The imported components in `WeatherLab.jsx` embed the existing map and weather lab. Plot calculations remain in those applications. The map accepts `?autoplay=1`. The weather lab accepts `?embed=histograms`, with optional `stage=pupa` and `units=C`. Histogram controls select life stage, temperature units and bin count. Missing temperature windows are excluded and counted explicitly.

The note in the Notes vault embeds the same two figures directly in Markdown. Obsidian renders the iframes in reading mode. It does not compile MDX. Localhost links need servers on the computer displaying the note and are not accessible from a phone through iCloud sync. The previous density figure and long MDX explanation were removed at Kyle's request.

The build compiles trusted local MDX and bundles React locally with esbuild. No CDN is required for the viewer or chart assets. The map background uses online OpenStreetMap tiles. Dependencies and generated bundles remain ignored. `package-lock.json` records the installed dependencies. No Obsidian plugin, web hosting or vault-wide format change is required.

The MDX approach follows the official [format guide](https://mdxjs.com/docs/what-is-mdx/) and [compiler reference](https://mdxjs.com/packages/mdx/). Ordinary notes use Obsidian's documented [web-page embeds](https://obsidian.md/help/Editing+and+formatting/Embed+web+pages).
