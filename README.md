# DirtyForge

**Describe the job. Build a complete, hardened Hermes Bot or team from one sentence.**

DirtyForge is a [Hermes Agent](https://github.com/DirtyDreams/hermes-agent) plugin combining:
- **Lazy Blueprint Router** (`data/blueprints.json`, 279 specialist roles from `agency-agents`)
- **Hybrid `SOUL.md` Metaprompt Compiler** (Show-don't-tell, Artifact Isolation, Anti-Injection)
- **`oh-my-hermes` (`omh`) Project Memory** in `auto-safe` mode + candidate review (`dirty_forge_omh_review`)
- **Deterministic `pre_tool_call` Sentinel** (`send`/`spend`/`destroy` gates, argument limits, shell command-injection detection, secret scanner)
- **Shared Policy Drift Detection & Sync** (`shared/BOT-POLICY.md` with SHA-256 fingerprint)
- **Teams, Handoffs, Journals & Portability** (`create_team`, `handoff_bot`, `agent_journal`, `copy_bot`, `teach_bot`, `share_bot`, `import_bot`)

## Install

```bash
hermes plugins install DirtyDreams/dirty-forge
hermes plugins enable dirty-forge
hermes gateway restart
hermes dirty-forge-doctor
```

## Development & Tests

```bash
python3 -m unittest discover -s tests -v
```
