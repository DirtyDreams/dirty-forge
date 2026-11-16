"""OpenAI-style tool schemas for DirtyForge."""

SEARCH_BLUEPRINTS = {
    "name": "dirty_forge_search_blueprints",
    "description": "Search DirtyForge's on-disk specialist blueprints and get the SOUL.md metaprompt guide before creating a Bot.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language role or capability query."},
            "division": {"type": "string", "description": "Optional division filter (e.g. engineering, marketing, research)."},
            "limit": {"type": "integer", "description": "Maximum blueprint matches to return (default 5)."},
        },
        "required": ["query"],
    },
}

CREATE_BOT = {
    "name": "dirty_forge_create_bot",
    "description": "Create a complete, isolated Hermes Bot profile with compiled SOUL.md, OMH auto-safe memory, sentinel guardrails, journal, and routines.",
    "parameters": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string", "description": "Unique Proper Case character name (e.g. Quill, Kairo, Nova)."},
            "role": {"type": "string", "description": "Short role title (e.g. Research Analyst, DevOps Engineer)."},
            "description": {"type": "string", "description": "One-sentence summary of what the Bot does."},
            "one_job": {"type": "string", "description": "Concrete definition of the Bot's single job and what 'done' looks like."},
            "soul_md": {"type": "string", "description": "Optional pre-compiled SOUL.md. If omitted, DirtyForge compiles it via metaprompt/blueprint."},
            "blueprint_slug": {"type": "string", "description": "Optional blueprint slug from dirty_forge_search_blueprints."},
            "avatar_kind": {"type": "string", "description": "Avatar shape: sun, cloud, boxy, droplet, star, or leaf."},
            "toolsets": {"type": "array", "items": {"type": "string"}, "description": "Extra toolsets beyond base (e.g. terminal, cronjob, image_gen)."},
            "memory": {"type": "array", "items": {"type": "string"}, "description": "Starter facts for MEMORY.md."},
            "routines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "schedule": {"type": "string"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["schedule", "prompt"],
                },
                "description": "Optional cron routines.",
            },
            "omh_memory_mode": {"type": "string", "description": "Override OMH memory mode: auto-safe, review-first, or off."},
            "escalate_to": {"type": "string", "description": "Who makes final calls (default: the user)."},
            "draft": {"type": "boolean", "description": "If true, keep cron routines disabled until eval_bot passes."},
        },
        "required": ["display_name", "role"],
    },
}

LIST_BOTS = {
    "name": "dirty_forge_list_bots",
    "description": "List existing Hermes Bot profiles on this machine.",
    "parameters": {
        "type": "object",
        "properties": {
            "include_hidden": {"type": "boolean", "description": "Include hidden Bots (default false)."},
        },
        "required": [],
    },
}

UPDATE_BOT = {
    "name": "dirty_forge_update_bot",
    "description": "Update an existing Bot's display name, avatar, toolsets, or append instructions to its SOUL.md.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile id or name."},
            "display_name": {"type": "string", "description": "New Proper Case display name."},
            "avatar_kind": {"type": "string", "description": "New avatar_kind."},
            "toolsets": {"type": "array", "items": {"type": "string"}, "description": "Updated extra toolsets."},
            "soul_append": {"type": "string", "description": "Markdown block to append to SOUL.md."},
            "soul_replace": {
                "type": "string",
                "description": "Full replacement of SOUL.md. Prefer this over soul_append for a real edit.",
            },
            "allow_restricted_toolsets": {
                "type": "boolean",
                "description": "Grant send/spend/destroy toolsets despite approvals being enforced.",
            },
        },
        "required": ["name"],
    },
}

ROLLBACK_BOT = {
    "name": "dirty_forge_rollback",
    "description": (
        "Restore a Bot's SOUL.md, config.yaml and profile.yaml from its newest snapshot (or a named "
        "one). The current state is snapshotted first, so a rollback can itself be undone."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile id or name."},
            "stamp": {
                "type": "string",
                "description": "Snapshot directory name to restore; omit or 'last' for the newest.",
            },
        },
        "required": ["name"],
    },
}

CHECK_BOTS = {
    "name": "dirty_forge_check_bots",
    "description": "Read-only health check across all Bots: SOUL.md, shared policy drift, OMH memory mode, and sentinel status.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

JOURNAL = {
    "name": "dirty_forge_journal",
    "description": "Write or read entries in a Bot's append-only daily work journal.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "'write' or 'read'."},
            "name": {"type": "string", "description": "Target Bot profile name (defaults to current profile)."},
            "status": {"type": "string", "description": "For write: planned, progress, completed, blocked, or failed."},
            "goal": {"type": "string", "description": "For write: concise goal."},
            "outcome": {"type": "string", "description": "For write: observable result."},
            "evidence": {"type": "string", "description": "Optional evidence/paths/links."},
            "next_step": {"type": "string", "description": "Optional next step."},
            "date": {"type": "string", "description": "For read: optional YYYY-MM-DD filter."},
            "limit": {"type": "integer", "description": "For read: max entries to return."},
        },
        "required": ["action"],
    },
}

ASK_BOT = {
    "name": "dirty_forge_ask_bot",
    "description": "Ask another Hermes Bot a question via its profile and return its reply.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Target Bot profile name."},
            "question": {"type": "string", "description": "Question or prompt to send."},
        },
        "required": ["name", "question"],
    },
}

HIDE_BOT = {
    "name": "dirty_forge_hide_bot",
    "description": "Hide or unhide a Bot in the Hermes Bots roster.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "hidden": {"type": "boolean", "description": "True to hide, false to unhide."},
        },
        "required": ["name"],
    },
}

DELETE_BOT = {
    "name": "dirty_forge_delete_bot",
    "description": "Permanently delete a Bot profile (requires allow_delete: true in plugin config; creates .tar.gz backup first).",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact Bot profile name to delete."},
        },
        "required": ["name"],
    },
}

CREATE_TEAM = {
    "name": "dirty_forge_create_team",
    "description": "Build a team of Hermes Bots (optional lead + up to 6 specialists) with per-member rollback and lead roster memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "team": {"type": "string", "description": "Team label (e.g. Growth, Platform)."},
            "lead_name": {"type": "string", "description": "Existing Bot profile name to act as team lead."},
            "lead": {"type": "object", "description": "Or a create_bot spec to build a new lead Bot."},
            "members": {"type": "array", "items": {"type": "object"}, "description": "List of specialist Bot specs."},
        },
        "required": ["members"],
    },
}

HANDOFF_BOT = {
    "name": "dirty_forge_handoff_bot",
    "description": "Transfer end-to-end ownership of a task to another Bot with secret scanning, journal logging, and ack tracking.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Target Bot profile name."},
            "task": {"type": "string", "description": "Task description the receiving Bot now owns."},
            "context": {"type": "string", "description": "Optional context, links, or constraints."},
        },
        "required": ["to", "task"],
    },
}

COPY_BOT = {
    "name": "dirty_forge_copy_bot",
    "description": "Duplicate an existing Bot under a new Proper Case display_name.",
    "parameters": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Existing Bot profile name."},
            "display_name": {"type": "string", "description": "New Proper Case display name."},
            "role": {"type": "string", "description": "Optional new role title."},
        },
        "required": ["source", "display_name"],
    },
}

TEACH_BOT = {
    "name": "dirty_forge_teach_bot",
    "description": "Teach a Bot a repeatable skill by writing a validated SKILL.md into its profile.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Target Bot profile name."},
            "skill_name": {"type": "string", "description": "Skill slug (e.g. weekly-audit)."},
            "skill_md": {"type": "string", "description": "Full Markdown skill instructions."},
        },
        "required": ["name", "skill_name", "skill_md"],
    },
}

SHARE_BOT = {
    "name": "dirty_forge_share_bot",
    "description": "Export a Bot as a secret-scanned .dirtyforge.json template or a full .tar.gz backup.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "mode": {"type": "string", "description": "'template' (default) or 'backup'."},
            "out_path": {"type": "string", "description": "Optional output file path."},
        },
        "required": ["name"],
    },
}

IMPORT_BOT = {
    "name": "dirty_forge_import_bot",
    "description": "Import a Bot from a secret-scanned .dirtyforge.json template file.",
    "parameters": {
        "type": "object",
        "properties": {
            "source_path": {"type": "string", "description": "Path to .dirtyforge.json template."},
            "display_name": {"type": "string", "description": "Optional override display_name."},
        },
        "required": ["source_path"],
    },
}

SYNC_POLICIES = {
    "name": "dirty_forge_sync_policies",
    "description": "Propagate the canonical shared/BOT-POLICY.md to all Bots whose policy block has drifted.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

OMH_REVIEW = {
    "name": "dirty_forge_omh_review",
    "description": "List, approve, or reject queued OMH project memory candidates (.omh/memory/candidates) for a Bot.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "action": {"type": "string", "description": "'list', 'approve', or 'reject'."},
            "candidate_id": {"type": "string", "description": "Candidate ID (for approve/reject)."},
        },
        "required": ["name", "action"],
    },
}

FIT_TEST = {
    "name": "dirty_forge_fit_test",
    "description": "Run a 5-question Fit Test to determine the smallest sufficient setup (reuse, skill, routine, single_bot, or team) and get a Task Card template.",
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What the user wants accomplished."},
            "recurring": {"type": "boolean", "description": "Whether this runs on a schedule."},
            "needs_separate_state_or_config": {"type": "boolean", "description": "Whether isolated memory, SOUL.md, or toolsets are required."},
            "multiple_distinct_roles": {"type": "boolean", "description": "Whether multiple separate roles need coordination."},
        },
        "required": ["goal"],
    },
}

EVAL_BOT = {
    "name": "dirty_forge_eval_bot",
    "description": "Run pass/fail evaluation cases (typical, missing_data, boundary, out_of_scope, unauthorized_action) against a Bot and save an audit report.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "cases": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Evaluation cases with id, kind, prompt, must_contain, must_not_contain, or expected_sentinel_tool.",
            },
        },
        "required": ["name", "cases"],
    },
}

ACTIVATE_BOT = {
    "name": "dirty_forge_activate_bot",
    "description": "Enable draft cron routines for a Bot after eval_bot passes (100% pass rate), unless force=true.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "force": {"type": "boolean", "description": "Bypass the eval_bot 100% pass requirement (default false)."},
        },
        "required": ["name"],
    },
}

REQUEST_TAKEOVER = {
    "name": "dirty_forge_request_takeover",
    "description": "Pause autonomous work and request human operator takeover for a Bot, recording context and a journal blocker.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "reason": {"type": "string", "description": "Why human intervention is needed."},
            "context": {"type": "string", "description": "Optional diagnostic or state summary."},
        },
        "required": ["name", "reason"],
    },
}

DELEGATE_OUTSIDE = {
    "name": "dirty_forge_delegate_outside",
    "description": "Delegate a bounded task to an allowlisted external CLI (e.g. codex, claude, aider). Disabled unless allow_external_delegation=true.",
    "parameters": {
        "type": "object",
        "properties": {
            "cli": {"type": "string", "description": "Allowlisted external CLI executable name."},
            "task": {"type": "string", "description": "Task prompt to send to the external CLI."},
            "cwd": {"type": "string", "description": "Optional working directory."},
        },
        "required": ["cli", "task"],
    },
}

BOT_METRICS = {
    "name": "dirty_forge_bot_metrics",
    "description": "Inspect per-Bot tool telemetry and circuit breaker state, or reset a tripped circuit breaker.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Bot profile name."},
            "reset_breaker": {"type": "boolean", "description": "If true, reset a tripped circuit breaker and counters."},
        },
        "required": ["name"],
    },
}

INTERVIEW = {
    "name": "dirty_forge_interview",
    "description": "Run a stateful, adaptive 5-block discovery interview before creating a Bot. Returns the next missing question with a recommended answer, and generates create_bot_spec + starter eval_cases once complete.",
    "parameters": {
        "type": "object",
        "properties": {
            "intake_id": {"type": "string", "description": "Optional existing intake session ID to continue."},
            "answers": {"type": "object", "description": "Answers collected so far (e.g. role, one_job, target_user, exact_output_format, sources_of_truth, out_of_scope, escalate_when, display_name)."},
            "include_optional": {"type": "boolean", "description": "Ask optional enrichment questions after required fields (default true)."},
        },
        "required": [],
    },
}
