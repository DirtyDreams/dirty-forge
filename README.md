# DirtyForge

**Describe the job. Fit-test first, build a hardened Hermes Bot or team, and verify it with an evaluation gate.**

DirtyForge is a [Hermes Agent](https://github.com/DirtyDreams/hermes-agent) plugin (`>=0.21`) combining:
- **5-Question Fit Test & Task Card** (`dirty_forge_fit_test`) — recommends the smallest sufficient setup (`reuse_existing`, `skill`, `routine`, `single_bot`, or `team`) before creating a profile
- **Lazy Blueprint Router** (`data/blueprints.json`, 279 specialist roles from `agency-agents`)
- **Hybrid `SOUL.md` Metaprompt Compiler** (Show-don't-tell, Artifact Isolation, Anti-Injection)
- **`oh-my-hermes` (`omh`) Project Memory** in `auto-safe` mode + candidate review (`dirty_forge_omh_review`)
- **Deterministic `pre_tool_call` Sentinel** (`send`/`spend`/`destroy` gates, argument limits, shell command-injection detection, secret scanner, and `SKILL.md` escalation scanner)
- **Bot Evaluation Gate** (`dirty_forge_eval_bot`) — runs pass/fail cases (`typical`, `missing_data`, `boundary`, `out_of_scope`, `unauthorized_action`) and saves audit reports
- **Shared Policy Drift Detection & Sync** (`shared/BOT-POLICY.md` with SHA-256 fingerprint)
- **Teams, Handoffs, Journals & Portability** (`create_team`, `handoff_bot`, `agent_journal`, `copy_bot`, `teach_bot`, `share_bot`, `import_bot`)

---

## Install

```bash
hermes plugins install DirtyDreams/dirty-forge
hermes plugins enable dirty-forge
hermes gateway restart
hermes dirty-forge-doctor
```

---

## Tools Exposed to Hermes (`toolset: dirty_forge`)

| Tool | Purpose |
|---|---|
| `dirty_forge_fit_test` | 5-question Fit Test + Task Card template before provisioning |
| `dirty_forge_search_blueprints` | Search 279 specialist blueprints + retrieve `SOUL.md` metaprompt guide |
| `dirty_forge_create_bot` | Provision an isolated Bot profile (`SOUL.md`, `omh` `auto-safe`, `sentinel`, `journal`, `cron`, `draft` mode) |
| `dirty_forge_eval_bot` | Run pass/fail evaluation cases and save an audit report under `<profile>/evals/` |
| `dirty_forge_activate_bot` | Enable `draft` cron routines after `eval_bot` passes 100% (or with `force=true`) |
| `dirty_forge_create_team` | Build a lead Bot + up to 6 specialists with per-member rollback |
| `dirty_forge_list_bots` | List existing Bot profiles |
| `dirty_forge_update_bot` | Update `display_name`, `avatar_kind`, `toolsets`, or append to `SOUL.md` |
| `dirty_forge_copy_bot` | Clone an existing Bot and its taught skills under a new identity |
| `dirty_forge_teach_bot` | Teach a `SKILL.md` (with privilege-escalation & secret scanning + >3 skill warning) |
| `dirty_forge_share_bot` | Export a secret-scanned `.dirtyforge.json` template or `.tar.gz` backup |
| `dirty_forge_import_bot` | Import a secret-scanned `.dirtyforge.json` template |
| `dirty_forge_check_bots` | Read-only health check (policy drift, `omh`, `sentinel`) |
| `dirty_forge_sync_policies` | Propagate canonical `shared/BOT-POLICY.md` to drifted Bots |
| `dirty_forge_omh_review` | List, approve, or reject `.omh/memory/candidates/*.json` |
| `dirty_forge_journal` | Write or read append-only daily work journal entries |
| `dirty_forge_ask_bot` | Ask another Bot a question (respecting `CORE_TOOL_DEADLINE`) |
| `dirty_forge_handoff_bot` | Transfer end-to-end task ownership with secret & prompt-injection scan, journal, and ack tracking |
| `dirty_forge_request_takeover` | Pause autonomous work and request human operator takeover (`takeovers/` + journal) |
| `dirty_forge_delegate_outside` | Opt-in delegation to allowlisted external CLIs (`codex`, `claude`, `aider`) |
| `dirty_forge_bot_metrics` | Inspect per-Bot telemetry (`metrics.jsonl`) or reset a tripped circuit breaker |
| `dirty_forge_hide_bot` | Hide or unhide a Bot in the roster (syncs `profile.yaml` `ui_meta`) |
| `dirty_forge_delete_bot` | Permanently delete a Bot (disabled by default; requires `allow_delete: true`, creates `.tar.gz` backup) |

---

## Configuration (`config_schema`)

| Key | Default | Description |
|---|---|---|
| `inherit_model` | `true` | Inherit launching profile's model |
| `fallback_model` | `{}` | Fallback model block (`{default, provider, base_url}`) |
| `probe_local_models` | `false` | Probe local OpenAI-compatible servers |
| `omh_memory_mode` | `"auto-safe"` | Default OMH memory mode (`auto-safe`, `review-first`, `off`) |
| `inherit_plugins` | `["omh"]` | Root plugins copied & enabled in new Bots (without `.env` or secrets) |
| `enforce_approvals` | `true` | Install `dirty-forge-sentinel` (`pre_tool_call` gate + circuit breaker) |
| `journal_enabled` | `true` | Enable append-only daily work journal |
| `ack_reactions` | `true` | Begin Bot replies with status emoji (`👀`/`💬`/`✅`/`✋`/`⚠️`/`⏳`) |
| `ack_tapback` | `true` | Desktop message reactions (`pre_llm_call`/`post_llm_call`) |
| `workspace_survey` | `true` | Shallow read-only workspace survey into `MEMORY.md` |
| `workspace_roots` | `[]` | Extra workspace roots to survey |
| `install_gateway` | `true` | Check gateway status and trigger restart |
| `allow_secrets` | `false` | Operator-only override for `share_bot`/`import_bot` |
| `allow_delete` | `false` | Allow `dirty_forge_delete_bot` |
| `backup_before_delete` | `true` | Export `.tar.gz` backup before deletion |
| `allow_external_delegation` | `false` | Allow `dirty_forge_delegate_outside` to invoke allowlisted external CLIs |
| `allowed_external_clis` | `["codex", "claude", "aider"]` | Executable names permitted for `dirty_forge_delegate_outside` |
| `circuit_breaker_max_calls` | `40` | Max tool calls before sentinel circuit breaker trips |
| `circuit_breaker_max_errors` | `5` | Max consecutive tool errors before sentinel circuit breaker trips |

---

## Development & Tests

```bash
python3 -m unittest discover -s tests -v
uvx ruff check .
```
