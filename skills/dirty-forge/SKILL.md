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
2. **Conduct a thorough adaptive discovery interview** using `dirty_forge_interview` **before** creating any Bot:
   - Pre-fill `answers` with everything the user already specified so you never ask redundant questions.
   - Ask `next_question` **one question at a time** (including its `recommended` option) across the 5 blocks: (1) Goal & Fit, (2) Inputs/Outputs/Sources, (3) Boundaries & Good/Bad Examples, (4) Tools/MCP/Safety & Escalation, (5) Identity/Memory/Schedule.
   - Continue until `ready_to_create: true` and you have a validated `create_bot_spec` and starter `eval_cases`.
3. Call `dirty_forge_search_blueprints` to get the closest specialist blueprint and metaprompt guide.
4. Call `dirty_forge_create_bot` using `create_bot_spec` (with `intake_id`, minimal initial toolsets, and `draft: true` if routines are attached).
5. Run `dirty_forge_eval_bot` using the generated `eval_cases` (`typical`, `missing_data`, `boundary`, `out_of_scope`, `unauthorized_action`) before treating the Bot as production-ready.
6. If provisioned with `draft: true`, call `dirty_forge_activate_bot` once `eval_bot` passes 100% to enable cron routines.
