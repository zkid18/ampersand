# Open-Source Capture-to-Markdown Product

## One-liner
Open-source capture layer that turns anything from the web into markdown files you own.

## Why now
- Pocket shut down July 2025 — millions of displaced users
- Omnivore also shut down
- Readwise is paid, closed-source, syncs highlights only (not full content)
- Obsidian Web Clipper is browser-only (no newsletters, no video, no mobile)
- "Own your data" sentiment at all-time high
- AI makes content extraction/summarization dramatically better
- No credible open-source player in this space

## The gap

| Need                      | Readwise | Obsidian Clipper | Raindrop | THIS PRODUCT |
|---------------------------|----------|------------------|----------|--------------|
| Articles                  | Yes      | Yes              | Link only| Yes          |
| Videos (transcript)       | Yes      | No               | No       | Yes          |
| Newsletters               | Yes      | No               | No       | Yes          |
| Frictionless capture      | Good     | Good (browser)   | Good     | Great        |
| Obsidian sync             | Highlights only | Native     | Manual   | Full content |
| Full content as markdown  | No       | Yes              | No       | Yes          |
| Open source / own data    | No       | Yes              | No       | Yes          |
| Price                     | $8/mo    | Free             | Freemium | Free / self-host |

## Architecture

```
CAPTURE                        PROCESS              OUTPUT
───────                        ───────              ──────
Browser extension  ──┐
                     ├──→  Extract + Clean  ──→  Markdown files
Email address      ──┤     (Readability,         (in a folder,
(newsletters)        │      yt-dlp,               git repo, or
                     │      AI summary)           synced vault)
Share sheet /      ──┘
paste a URL
```

### Processing pipeline
1. Fetch & extract (Readability)
2. YouTube? → grab transcript
3. Email? → parse HTML body
4. Convert to clean markdown
5. Generate frontmatter metadata
6. (V2: AI summarize & auto-tag)

### Storage / Sync options
- Write to local folder (Obsidian vault)
- Push to git repo
- S3 / cloud folder
- All of the above

## Output format

```markdown
---
title: "Article Title"
source: https://example.com/article
type: article | video | newsletter
captured: 2026-02-17T10:30:00Z
author: Author Name
tags: []
---

# Article Title

Full, clean content in markdown...
```

## MVP (V1) scope

### In V1
- [ ] CLI tool: takes a URL → outputs .md file (core engine)
- [ ] Browser extension (clip article with one click)
- [ ] Paste/send a URL (API endpoint)
- [ ] Newsletter email forwarding / parsing
- [ ] YouTube transcript extraction
- [ ] Full content → clean markdown conversion
- [ ] Obsidian vault sync (write to local folder)

### V2
- [ ] AI summaries / auto-tagging
- [ ] Mobile app / share sheet
- [ ] Web reading UI
- [ ] Highlights / annotations

### V3
- [ ] Team / shared collections
- [ ] Search across library
- [ ] Graph / connections view

## Open decisions
1. **Name** — TBD
2. **Hosted vs self-hosted only** — Wallabag model (open source core + cheap hosted option) recommended
3. **Tech stack** — TBD (TypeScript, Python, Go, Rust?)
4. **Suggested starting point** — CLI tool that takes a URL and outputs a .md file. Everything else wraps around that core.

## Competitive positioning
- **vs Readwise**: Open source, free, full content (not just highlights), you own your data
- **vs Obsidian Clipper**: All content types (not just browser), newsletters, video transcripts
- **vs Raindrop**: Full content extraction, not just bookmarks
- **vs Wallabag**: Modern UX, AI-native, multi-source (not just articles)
- **vs dead Pocket**: You own your data, will never shut down, markdown-native
