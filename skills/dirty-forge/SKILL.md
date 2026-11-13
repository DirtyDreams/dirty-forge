---
name: dirty-forge
description: "Design and provision a complete, hardened Hermes Bot from one sentence using DirtyForge (blueprint search, hybrid SOUL.md compiler, OMH auto-safe memory, and sentinel guardrails)."
version: 0.1.0
author: DirtyDreams
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, bot-mode, profiles, dirty-forge, omh, sentinel]
---

# DirtyForge

Build a new Hermes Bot only when a persistent responsibility, state, or configuration boundary is justified.

## Workflow
1. Call `dirty_forge_list_bots` to see if an existing Bot already covers the job.
2. Call `dirty_forge_search_blueprints` with the requested role to retrieve the closest specialist blueprint and metaprompt guide.
3. Choose a unique, Proper Case character `display_name` (e.g. `Quill`, `Kairo`, `Nova` — never generic role words like `Writer` or `Coder`) and a fitting `avatar_kind` (`sun`, `cloud`, `boxy`, `droplet`, `star`, `leaf`).
4. Compile a crisp `soul_md` following the returned metaprompt guide (Show-don't-tell, Artifact Isolation, Anti-Injection, concrete `## Your one job`, `## How you work`, `## Voice`, `## Never`, `## Escalate to`), or pass only `role` + `description` to let DirtyForge's hybrid compiler build it.
5. Call `dirty_forge_create_bot`. Report the created Bot's name, job, model, OMH memory mode (`auto-safe`), toolsets, routines, and gateway status concisely.
