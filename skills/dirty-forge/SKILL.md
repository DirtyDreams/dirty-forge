---
name: dirty-forge
description: "Design, fit-test, provision, and evaluate a complete, hardened Hermes Bot or team using DirtyForge."
version: 1.1.0
author: DirtyDreams
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, bot-mode, profiles, dirty-forge, omh, sentinel, eval]
---

# DirtyForge

Choose the **smallest sufficient setup** before creating a new Bot profile.

## Workflow
1. Call `dirty_forge_list_bots` and `dirty_forge_fit_test` to decide between reusing an existing Bot, writing a `SKILL.md` (2–3 focused skills max), adding a cron routine, creating a single Bot, or building a team.
2. When a new Bot is justified, fill a concise Task Card (one main result, inputs, exact output format, out-of-scope, sources of truth, forbidden tools, approvals, escalation).
3. Call `dirty_forge_search_blueprints` to get the closest specialist blueprint and metaprompt guide.
4. Pick a unique Proper Case character `display_name` (`Quill`, `Kairo`, `Nova`) and `avatar_kind`, then call `dirty_forge_create_bot` with minimal initial toolsets (add `terminal`, `cronjob`, or publishing only after testing).
5. Run `dirty_forge_eval_bot` with representative pass/fail cases (`typical`, `missing_data`, `boundary`, `out_of_scope`, `unauthorized_action`) before treating the Bot as production-ready.
6. If provisioned with `draft: true`, call `dirty_forge_activate_bot` once `eval_bot` passes 100% to enable cron routines.
