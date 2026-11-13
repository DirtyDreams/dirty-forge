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
