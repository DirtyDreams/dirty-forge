import {
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  haptic,
  host,
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const TABS = [
  { id: 'roster', label: 'Roster & Health' },
  { id: 'interview', label: 'Interview & Forge' },
  { id: 'evals', label: 'Evals & Telemetry' },
  { id: 'governance', label: 'Governance (OMH / Takeovers / Journal)' },
]

function notifyInfo(message) {
  host.notify?.({ kind: 'info', message })
}

function notifyError(message) {
  if (typeof host.notifyError === 'function') {
    host.notifyError(message)
  } else {
    host.notify?.({ kind: 'error', message })
  }
}

function badgeClass(tone) {
  const base = 'inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium border '
  if (tone === 'ok') return base + 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
  if (tone === 'warn') return base + 'border-amber-500/40 bg-amber-500/10 text-amber-300'
  if (tone === 'err') return base + 'border-rose-500/40 bg-rose-500/10 text-rose-400'
  return base + 'border-(--ui-border) bg-(--ui-bg-secondary) text-(--ui-text-secondary)'
}

function btnClass(variant = 'default') {
  const base =
    'inline-flex items-center justify-center rounded px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 cursor-pointer '
  if (variant === 'primary') {
    return base + 'bg-blue-600 text-white hover:bg-blue-500'
  }
  if (variant === 'danger') {
    return base + 'border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20'
  }
  return base + 'border border-(--ui-border) bg-(--ui-bg-secondary) text-(--ui-text-primary) hover:opacity-85'
}

function inputClass() {
  return 'w-full rounded border border-(--ui-border) bg-(--ui-bg-primary) px-2.5 py-1.5 text-xs text-(--ui-text-primary) outline-none focus:border-blue-500'
}

function DirtyForgeStatusChip({ ctx }) {
  const [summary, setSummary] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const res = await ctx.rest('/summary')
      if (res && res.ok) setSummary(res)
    } catch {
      // Backend may be starting up; fail silently in status bar.
    }
  }, [ctx])

  useEffect(() => {
    void refresh()
    const stop = ctx.setInterval(() => {
      void refresh()
    }, 15000)
    return stop
  }, [ctx, refresh])

  const alerts = (summary?.tripped_breakers || 0) + (summary?.pending_takeovers || 0)
  const label = summary
    ? `Bots: ${summary.total_bots}${alerts > 0 ? ` · ⚠ ${alerts}` : ''}`
    : 'DirtyForge'

  return jsx('button', {
    type: 'button',
    className:
      'px-1.5 text-[0.6875rem] ' +
      (alerts > 0 ? 'text-amber-300 font-medium' : 'text-(--ui-text-tertiary) hover:text-(--ui-text-primary)'),
    title: 'Open DirtyForge',
    onClick: () => {
      haptic?.('tap')
      host.navigate('/dirty-forge')
    },
    children: label,
  })
}

function RosterTab({ ctx, bots, onRefresh, onSelectBot }) {
  const [busy, setBusy] = useState('')
  const [confirmDelete, setConfirmDelete] = useState('')
  const [importPath, setImportPath] = useState('')
  const [importName, setImportName] = useState('')
  const [inspectData, setInspectData] = useState(null)
  const [editDisplay, setEditDisplay] = useState('')
  const [editAppendSoul, setEditAppendSoul] = useState('')

  async function openInspect(botName) {
    setBusy(`insp:${botName}`)
    try {
      const res = await ctx.rest(`/bots/${botName}/files`)
      if (res?.ok) {
        setInspectData(res)
        setEditDisplay(res.display_name || botName)
        setEditAppendSoul('')
      } else {
        notifyError(res?.error || 'Failed to load Bot files')
      }
    } catch (err) {
      notifyError(String(err?.message || err))
    } finally {
      setBusy('')
    }
  }

  async function runAction(key, fn, okMsg) {
    setBusy(key)
    try {
      const res = await fn()
      if (res && res.ok === false) {
        notifyError(res.error || 'Action failed')
      } else if (okMsg) {
        notifyInfo(okMsg)
      }
      await onRefresh()
    } catch (err) {
      notifyError(String(err?.message || err))
    } finally {
      setBusy('')
    }
  }

  return jsxs('div', {
    className: 'flex flex-col gap-4',
    children: [
      jsxs('div', {
        className: 'flex flex-wrap items-center justify-between gap-2',
        children: [
          jsxs('div', {
            className: 'text-xs text-(--ui-text-secondary)',
            children: [`Total Bots: ${bots.length}`],
          }),
          jsxs('div', {
            className: 'flex flex-wrap gap-2',
            children: [
              jsx('button', {
                type: 'button',
                className: btnClass('default'),
                disabled: Boolean(busy),
                onClick: () => runAction('sync', () => ctx.rest('/policies/sync', { method: 'POST' }), 'Policies synced'),
                children: busy === 'sync' ? 'Syncing…' : 'Sync All Policies',
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('default'),
                disabled: Boolean(busy),
                onClick: () => onRefresh(),
                children: 'Refresh',
              }),
            ],
          }),
        ],
      }),
      bots.length === 0
        ? jsx('div', {
            className: 'rounded border border-(--ui-border) p-6 text-center text-xs text-(--ui-text-tertiary)',
            children: 'No Bots created yet. Switch to "Interview & Forge" to build your first Bot.',
          })
        : jsx('div', {
            className: 'grid grid-cols-1 gap-3 md:grid-cols-2',
            children: bots.map((bot) =>
              jsxs(
                'div',
                {
                  className: 'flex flex-col gap-2.5 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
                  children: [
                    jsxs('div', {
                      className: 'flex items-start justify-between gap-2',
                      children: [
                        jsxs('div', {
                          children: [
                            jsx('div', {
                              className: 'text-sm font-semibold text-(--ui-text-primary)',
                              children: bot.display_name || bot.name,
                            }),
                            jsx('div', {
                              className: 'text-[11px] text-(--ui-text-tertiary)',
                              children: `${bot.name} · ${bot.role || 'custom'}`,
                            }),
                          ],
                        }),
                        jsxs('div', {
                          className: 'flex flex-wrap gap-1',
                          children: [
                            jsx('span', {
                              className: badgeClass(bot.status === 'active' ? 'ok' : 'warn'),
                              children: bot.status || 'draft',
                            }),
                            bot.hidden
                              ? jsx('span', { className: badgeClass('default'), children: 'hidden' })
                              : null,
                          ],
                        }),
                      ],
                    }),
                    jsxs('div', {
                      className: 'flex flex-wrap gap-1.5',
                      children: [
                        jsx('span', {
                          className: badgeClass(bot.policy_in_sync ? 'ok' : 'warn'),
                          children: bot.policy_in_sync ? 'Policy: in sync' : 'Policy: drifted',
                        }),
                        jsx('span', {
                          className: badgeClass(bot.omh_configured ? 'ok' : 'default'),
                          children: `OMH: ${bot.omh_memory_mode || 'off'}`,
                        }),
                        jsx('span', {
                          className: badgeClass(bot.sentinel_installed ? 'ok' : 'warn'),
                          children: bot.sentinel_installed ? 'Sentinel: on' : 'Sentinel: off',
                        }),
                        bot.telemetry?.breaker_tripped
                          ? jsx('span', { className: badgeClass('err'), children: 'Breaker: TRIPPED' })
                          : jsx('span', {
                              className: badgeClass('default'),
                              children: `Calls: ${bot.telemetry?.total_calls || 0}`,
                            }),
                        bot.pending_takeovers > 0
                          ? jsx('span', {
                              className: badgeClass('err'),
                              children: `Takeovers: ${bot.pending_takeovers}`,
                            })
                          : null,
                      ],
                    }),
                    jsxs('div', {
                      className: 'flex flex-wrap gap-1.5 pt-1',
                      children: [
                        bot.status !== 'active'
                          ? jsx('button', {
                              type: 'button',
                              className: btnClass('primary'),
                              disabled: Boolean(busy),
                              onClick: () =>
                                runAction(
                                  `act:${bot.name}`,
                                  () => ctx.rest(`/bots/${bot.name}/activate`, { method: 'POST', body: { force: false } }),
                                  `Activated ${bot.name}`
                                ),
                              children: 'Activate',
                            })
                          : null,
                        bot.telemetry?.breaker_tripped
                          ? jsx('button', {
                              type: 'button',
                              className: btnClass('default'),
                              disabled: Boolean(busy),
                              onClick: () =>
                                runAction(
                                  `brk:${bot.name}`,
                                  () => ctx.rest(`/bots/${bot.name}/reset-breaker`, { method: 'POST' }),
                                  `Reset breaker for ${bot.name}`
                                ),
                              children: 'Reset Breaker',
                            })
                          : null,
                        jsx('button', {
                          type: 'button',
                          className: btnClass('default'),
                          onClick: () => void openInspect(bot.name),
                          children: 'Inspect',
                        }),
                        jsx('button', {
                          type: 'button',
                          className: btnClass('default'),
                          onClick: () => onSelectBot(bot.name, 'evals'),
                          children: 'Eval',
                        }),
                        jsx('button', {
                          type: 'button',
                          className: btnClass('default'),
                          onClick: () => onSelectBot(bot.name, 'governance'),
                          children: 'Govern',
                        }),
                        jsx('button', {
                          type: 'button',
                          className: btnClass('default'),
                          disabled: Boolean(busy),
                          onClick: () =>
                            runAction(
                              `hide:${bot.name}`,
                              () => ctx.rest(`/bots/${bot.name}/hide`, { method: 'POST', body: { hidden: !bot.hidden } }),
                              bot.hidden ? `Unhid ${bot.name}` : `Hid ${bot.name}`
                            ),
                          children: bot.hidden ? 'Unhide' : 'Hide',
                        }),
                        jsx('button', {
                          type: 'button',
                          className: btnClass('default'),
                          disabled: Boolean(busy),
                          onClick: () =>
                            runAction(
                              `share:${bot.name}`,
                              async () => {
                                const res = await ctx.rest(`/bots/${bot.name}/share`, {
                                  method: 'POST',
                                  body: { mode: 'template' },
                                })
                                if (res?.ok && res?.out_path) notifyInfo(`Exported to ${res.out_path}`)
                                return res
                              },
                              null
                            ),
                          children: 'Export',
                        }),
                        confirmDelete === bot.name
                          ? jsxs('span', {
                              className: 'inline-flex gap-1',
                              children: [
                                jsx('button', {
                                  type: 'button',
                                  className: btnClass('danger'),
                                  disabled: Boolean(busy),
                                  onClick: () => {
                                    setConfirmDelete('')
                                    void runAction(
                                      `del:${bot.name}`,
                                      () => ctx.rest(`/bots/${bot.name}`, { method: 'DELETE' }),
                                      `Deleted ${bot.name}`
                                    )
                                  },
                                  children: 'Confirm Delete',
                                }),
                                jsx('button', {
                                  type: 'button',
                                  className: btnClass('default'),
                                  onClick: () => setConfirmDelete(''),
                                  children: 'Cancel',
                                }),
                              ],
                            })
                          : jsx('button', {
                              type: 'button',
                              className: btnClass('danger'),
                              onClick: () => setConfirmDelete(bot.name),
                              children: 'Delete',
                            }),
                      ],
                    }),
                  ],
                },
                bot.name
              )
            ),
          }),
      inspectData
        ? jsxs('div', {
            className: 'flex flex-col gap-3 rounded border border-blue-500/40 bg-(--ui-bg-secondary) p-3',
            children: [
              jsxs('div', {
                className: 'flex items-center justify-between gap-2',
                children: [
                  jsx('div', {
                    className: 'text-xs font-semibold',
                    children: `Inspect & Update: ${inspectData.display_name} (${inspectData.name})`,
                  }),
                  jsx('button', {
                    type: 'button',
                    className: btnClass('default'),
                    onClick: () => setInspectData(null),
                    children: 'Close',
                  }),
                ],
              }),
              jsxs('div', {
                className: 'grid grid-cols-1 gap-2 md:grid-cols-3',
                children: [
                  jsx('input', {
                    className: inputClass(),
                    placeholder: 'Display name',
                    value: editDisplay,
                    onChange: (e) => setEditDisplay(e.target.value),
                  }),
                  jsx('input', {
                    className: inputClass(),
                    placeholder: 'Append note/rule to SOUL.md',
                    value: editAppendSoul,
                    onChange: (e) => setEditAppendSoul(e.target.value),
                  }),
                  jsx('button', {
                    type: 'button',
                    className: btnClass('primary'),
                    disabled: Boolean(busy),
                    onClick: () =>
                      runAction(
                        `upd:${inspectData.name}`,
                        async () => {
                          const body = { display_name: editDisplay.trim() }
                          if (editAppendSoul.trim()) body.append_soul = editAppendSoul.trim()
                          const res = await ctx.rest(`/bots/${inspectData.name}/update`, { method: 'POST', body })
                          if (res?.ok) await openInspect(inspectData.name)
                          return res
                        },
                        `Updated ${inspectData.name}`
                      ),
                    children: 'Save Update',
                  }),
                ],
              }),
              jsxs('div', {
                className: 'grid grid-cols-1 gap-2 lg:grid-cols-2',
                children: [
                  jsxs('div', {
                    className: 'flex flex-col gap-1',
                    children: [
                      jsx('div', { className: 'text-[11px] font-medium text-(--ui-text-tertiary)', children: 'SOUL.md' }),
                      jsx('pre', {
                        className: 'max-h-56 overflow-auto rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-[11px] whitespace-pre-wrap',
                        children: inspectData.soul_md || '(empty)',
                      }),
                    ],
                  }),
                  jsxs('div', {
                    className: 'flex flex-col gap-1',
                    children: [
                      jsx('div', { className: 'text-[11px] font-medium text-(--ui-text-tertiary)', children: 'MEMORY.md' }),
                      jsx('pre', {
                        className: 'max-h-56 overflow-auto rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-[11px] whitespace-pre-wrap',
                        children: inspectData.memory_md || '(empty)',
                      }),
                    ],
                  }),
                ],
              }),
            ],
          })
        : null,
      jsxs('div', {
        className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
        children: [
          jsx('div', { className: 'text-xs font-semibold', children: 'Import Bot Template (.dirtyforge.json)' }),
          jsxs('div', {
            className: 'grid grid-cols-1 gap-2 md:grid-cols-3',
            children: [
              jsx('input', {
                className: inputClass(),
                placeholder: 'Path to .dirtyforge.json',
                value: importPath,
                onChange: (e) => setImportPath(e.target.value),
              }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Optional new display name',
                value: importName,
                onChange: (e) => setImportName(e.target.value),
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('primary'),
                disabled: !importPath.trim() || Boolean(busy),
                onClick: () =>
                  runAction(
                    'import',
                    () =>
                      ctx.rest('/bots/import', {
                        method: 'POST',
                        body: { source_path: importPath.trim(), display_name: importName.trim() },
                      }),
                    'Bot imported'
                  ),
                children: 'Import Bot',
              }),
            ],
          }),
        ],
      }),
    ],
  })
}

function InterviewForgeTab({ ctx, onCreated }) {
  const [session, setSession] = useState(null)
  const [answerText, setAnswerText] = useState('')
  const [bpQuery, setBpQuery] = useState('')
  const [blueprints, setBlueprints] = useState([])
  const [selectedSlug, setSelectedSlug] = useState('')
  const [busy, setBusy] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [fitGoal, setFitGoal] = useState('')
  const [fitRecurring, setFitRecurring] = useState(true)
  const [fitSeparateState, setFitSeparateState] = useState(true)
  const [fitMultiRole, setFitMultiRole] = useState(false)
  const [fitResult, setFitResult] = useState(null)
  const [teamName, setTeamName] = useState('')
  const [leadRole, setLeadRole] = useState('')
  const [memberRoles, setMemberRoles] = useState('')

  async function runFitTest() {
    if (!fitGoal.trim()) return
    try {
      const res = await ctx.rest('/fit-test', {
        method: 'POST',
        body: {
          goal: fitGoal.trim(),
          recurring: fitRecurring,
          needs_separate_state_or_config: fitSeparateState,
          multiple_distinct_roles: fitMultiRole,
        },
      })
      setFitResult(res)
    } catch (err) {
      notifyError(String(err?.message || err))
    }
  }

  async function createTeamNow() {
    if (!teamName.trim() || !leadRole.trim()) return
    setBusy(true)
    setErrorMsg('')
    try {
      const members = memberRoles
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 6)
        .map((role) => ({ role }))
      const res = await ctx.rest('/teams', {
        method: 'POST',
        body: {
          team_name: teamName.trim(),
          lead: { role: leadRole.trim() },
          members,
        },
      })
      if (!res?.ok) {
        setErrorMsg(res?.error || 'Failed to create team')
      } else {
        notifyInfo(`Created team ${teamName.trim()}`)
        setTeamName('')
        setLeadRole('')
        setMemberRoles('')
        await onCreated(res.lead_profile_id || '')
      }
    } catch (err) {
      setErrorMsg(String(err?.message || err))
    } finally {
      setBusy(false)
    }
  }

  const startOrStep = useCallback(
    async (answers = null, intakeId = '') => {
      setBusy(true)
      setErrorMsg('')
      try {
        const res = await ctx.rest('/interview', {
          method: 'POST',
          body: { intake_id: intakeId, answers },
        })
        if (!res.ok) {
          setErrorMsg(res.error || 'Interview step failed')
        } else {
          setSession(res)
          setAnswerText('')
        }
      } catch (err) {
        setErrorMsg(String(err?.message || err))
      } finally {
        setBusy(false)
      }
    },
    [ctx]
  )

  useEffect(() => {
    void startOrStep(null, '')
  }, [startOrStep])

  async function searchBp() {
    if (!bpQuery.trim()) return
    try {
      const res = await ctx.rest(`/blueprints?query=${encodeURIComponent(bpQuery.trim())}&limit=8`)
      if (res?.ok) setBlueprints(res.matches || [])
    } catch (err) {
      notifyError(String(err?.message || err))
    }
  }

  async function createFromInterview() {
    if (!session?.create_bot_spec) return
    setBusy(true)
    setErrorMsg('')
    try {
      const spec = { ...session.create_bot_spec }
      if (selectedSlug) spec.blueprint_slug = selectedSlug
      const res = await ctx.rest('/bots', { method: 'POST', body: spec })
      if (!res.ok) {
        setErrorMsg(res.error || 'Failed to create Bot')
      } else {
        const botId = res.name || res.profile_id
        notifyInfo(`Created Bot ${botId || spec.display_name}`)
        await onCreated(botId)
      }
    } catch (err) {
      setErrorMsg(String(err?.message || err))
    } finally {
      setBusy(false)
    }
  }

  async function sendToChat() {
    if (!session?.create_bot_spec) return
    const text = `Create DirtyForge Bot using intake_id="${session.intake_id}" (${session.create_bot_spec.display_name}).`
    if (host.composer?.insertText) {
      await host.composer.insertText(null, text, { mode: 'block' })
      host.composer.focus?.(null)
      notifyInfo('Inserted into composer')
    } else {
      notifyInfo(text)
    }
  }

  const nextQ = session?.next_question
  const comp = session?.completeness || { required_answered: 0, required_total: 8 }
  const pct = comp.percent ?? comp.pct ?? Math.round(((comp.required_answered || 0) / Math.max(1, comp.required_total || 8)) * 100)

  return jsxs('div', {
    className: 'grid grid-cols-1 gap-4 lg:grid-cols-3',
    children: [
      jsxs('div', {
        className: 'flex flex-col gap-3 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3 lg:col-span-2',
        children: [
          jsxs('div', {
            className: 'flex items-center justify-between gap-2',
            children: [
              jsxs('div', {
                children: [
                  jsx('div', { className: 'text-sm font-semibold', children: 'Discovery Interview (5 Blocks)' }),
                  jsx('div', {
                    className: 'text-[11px] text-(--ui-text-tertiary)',
                    children: `Progress: ${comp.required_answered}/${comp.required_total} required (${pct}%)`,
                  }),
                ],
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('default'),
                disabled: busy,
                onClick: () => startOrStep(null, ''),
                children: 'Reset Interview',
              }),
            ],
          }),
          jsx('div', {
            className: 'h-1.5 w-full overflow-hidden rounded bg-(--ui-bg-primary)',
            children: jsx('div', {
              className: 'h-full bg-blue-500 transition-all',
              style: { width: `${pct}%` },
            }),
          }),
          errorMsg
            ? jsx('div', {
                className: 'rounded border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-300',
                children: errorMsg,
              })
            : null,
          nextQ
            ? jsxs('div', {
                className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-primary) p-3',
                children: [
                  jsxs('div', {
                    className: 'flex items-center justify-between gap-2',
                    children: [
                      jsx('span', { className: badgeClass('default'), children: nextQ.block_label || nextQ.block }),
                      jsx('span', {
                        className: 'text-[11px] text-(--ui-text-tertiary)',
                        children: nextQ.required ? 'Required' : 'Optional',
                      }),
                    ],
                  }),
                  jsx('div', { className: 'text-xs font-medium text-(--ui-text-primary)', children: nextQ.question }),
                  jsx('textarea', {
                    className: inputClass(),
                    rows: 3,
                    placeholder: `Recommended: ${nextQ.recommended_default}`,
                    value: answerText,
                    onChange: (e) => setAnswerText(e.target.value),
                  }),
                  jsxs('div', {
                    className: 'flex flex-wrap gap-2',
                    children: [
                      jsx('button', {
                        type: 'button',
                        className: btnClass('primary'),
                        disabled: busy || !answerText.trim(),
                        onClick: () => startOrStep({ [nextQ.field]: answerText.trim() }, session.intake_id),
                        children: busy ? 'Saving…' : 'Submit Answer',
                      }),
                      jsx('button', {
                        type: 'button',
                        className: btnClass('default'),
                        disabled: busy,
                        onClick: () => startOrStep({ [nextQ.field]: nextQ.recommended_default }, session.intake_id),
                        children: 'Use Recommended Default',
                      }),
                    ],
                  }),
                ],
              })
            : jsxs('div', {
                className: 'flex flex-col gap-2 rounded border border-emerald-500/40 bg-emerald-500/10 p-3',
                children: [
                  jsx('div', {
                    className: 'text-xs font-semibold text-emerald-300',
                    children: 'Interview Complete — Ready to Forge!',
                  }),
                  jsx('div', {
                    className: 'text-[11px] text-(--ui-text-secondary)',
                    children: `Generated ${(session?.eval_cases || []).length} starter eval cases and Task Card.`,
                  }),
                  jsxs('div', {
                    className: 'flex flex-wrap gap-2 pt-1',
                    children: [
                      jsx('button', {
                        type: 'button',
                        className: btnClass('primary'),
                        disabled: busy,
                        onClick: () => createFromInterview(),
                        children: busy ? 'Forging…' : 'Create Bot Now',
                      }),
                      jsx('button', {
                        type: 'button',
                        className: btnClass('default'),
                        onClick: () => sendToChat(),
                        children: 'Send Spec to Chat',
                      }),
                    ],
                  }),
                ],
              }),
          session?.task_card
            ? jsxs('details', {
                className: 'rounded border border-(--ui-border) p-2 text-xs',
                children: [
                  jsx('summary', { className: 'cursor-pointer font-medium', children: 'Current Task Card JSON' }),
                  jsx('pre', {
                    className: 'mt-2 max-h-48 overflow-auto text-[11px] text-(--ui-text-secondary)',
                    children: JSON.stringify(session.task_card, null, 2),
                  }),
                ],
              })
            : null,
        ],
      }),
      jsxs('div', {
        className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
        children: [
          jsx('div', { className: 'text-xs font-semibold', children: 'Specialist Blueprints (279)' }),
          jsxs('div', {
            className: 'flex gap-1.5',
            children: [
              jsx('input', {
                className: inputClass(),
                placeholder: 'e.g. code review, devops, security…',
                value: bpQuery,
                onChange: (e) => setBpQuery(e.target.value),
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('default'),
                onClick: () => searchBp(),
                children: 'Search',
              }),
            ],
          }),
          selectedSlug
            ? jsx('div', {
                className: 'text-[11px] text-blue-400',
                children: `Selected blueprint: ${selectedSlug}`,
              })
            : null,
          jsx('div', {
            className: 'flex max-h-72 flex-col gap-1.5 overflow-auto',
            children: blueprints.map((bp) =>
              jsxs(
                'button',
                {
                  type: 'button',
                  className:
                    'flex flex-col rounded border p-2 text-left text-xs transition-colors cursor-pointer ' +
                    (selectedSlug === bp.slug
                      ? 'border-blue-500 bg-blue-500/10'
                      : 'border-(--ui-border) bg-(--ui-bg-primary) hover:opacity-85'),
                  onClick: () => setSelectedSlug(bp.slug === selectedSlug ? '' : bp.slug),
                  children: [
                    jsx('span', { className: 'font-medium text-(--ui-text-primary)', children: bp.name || bp.slug }),
                    jsx('span', { className: 'text-[11px] text-(--ui-text-tertiary)', children: bp.division || bp.slug }),
                  ],
                },
                bp.slug
              )
            ),
          }),
        ],
      }),
      jsxs('div', {
        className: 'grid grid-cols-1 gap-4 lg:col-span-3 lg:grid-cols-2',
        children: [
          jsxs('div', {
            className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3 text-xs',
            children: [
              jsx('div', { className: 'font-semibold', children: 'Fit Test (Right-Size Before Forging)' }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Describe the job or workflow…',
                value: fitGoal,
                onChange: (e) => setFitGoal(e.target.value),
              }),
              jsxs('div', {
                className: 'flex flex-wrap gap-3 text-[11px]',
                children: [
                  jsxs('label', {
                    className: 'inline-flex items-center gap-1 cursor-pointer',
                    children: [
                      jsx('input', { type: 'checkbox', checked: fitRecurring, onChange: () => setFitRecurring(!fitRecurring) }),
                      jsx('span', { children: 'Recurring' }),
                    ],
                  }),
                  jsxs('label', {
                    className: 'inline-flex items-center gap-1 cursor-pointer',
                    children: [
                      jsx('input', {
                        type: 'checkbox',
                        checked: fitSeparateState,
                        onChange: () => setFitSeparateState(!fitSeparateState),
                      }),
                      jsx('span', { children: 'Separate state/config' }),
                    ],
                  }),
                  jsxs('label', {
                    className: 'inline-flex items-center gap-1 cursor-pointer',
                    children: [
                      jsx('input', { type: 'checkbox', checked: fitMultiRole, onChange: () => setFitMultiRole(!fitMultiRole) }),
                      jsx('span', { children: 'Multiple distinct roles' }),
                    ],
                  }),
                ],
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('default'),
                disabled: !fitGoal.trim(),
                onClick: () => void runFitTest(),
                children: 'Run Fit Test',
              }),
              fitResult
                ? jsxs('div', {
                    className: 'rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-[11px]',
                    children: [
                      jsx('div', { className: 'font-semibold', children: `Recommendation: ${fitResult.recommendation}` }),
                      jsx('div', { className: 'text-(--ui-text-tertiary)', children: fitResult.reason || '' }),
                    ],
                  })
                : null,
            ],
          }),
          jsxs('div', {
            className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3 text-xs',
            children: [
              jsx('div', { className: 'font-semibold', children: 'Create Multi-Bot Team' }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Team name (e.g. Release Squad)',
                value: teamName,
                onChange: (e) => setTeamName(e.target.value),
              }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Lead role (e.g. Release Manager)',
                value: leadRole,
                onChange: (e) => setLeadRole(e.target.value),
              }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Specialist roles, comma-separated (up to 6)',
                value: memberRoles,
                onChange: (e) => setMemberRoles(e.target.value),
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('primary'),
                disabled: busy || !teamName.trim() || !leadRole.trim(),
                onClick: () => void createTeamNow(),
                children: 'Create Team',
              }),
            ],
          }),
        ],
      }),
    ],
  })
}

function EvalsTab({ ctx, bots, selectedBot, setSelectedBot }) {
  const [evalRes, setEvalRes] = useState(null)
  const [busy, setBusy] = useState(false)

  const target = selectedBot || bots[0]?.name || ''

  async function runEval() {
    if (!target) return
    setBusy(true)
    try {
      const res = await ctx.rest(`/bots/${target}/eval`, { method: 'POST', body: {} })
      setEvalRes(res)
      if (res?.ok === false) notifyError(res.error || 'Eval failed')
    } catch (err) {
      notifyError(String(err?.message || err))
    } finally {
      setBusy(false)
    }
  }

  const botObj = bots.find((b) => b.name === target)

  return jsxs('div', {
    className: 'flex flex-col gap-3',
    children: [
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-2',
        children: [
          jsx('select', {
            className: inputClass() + ' max-w-xs',
            value: target,
            onChange: (e) => setSelectedBot(e.target.value),
            children:
              bots.length === 0
                ? jsx('option', { value: '', children: 'No Bots available' })
                : bots.map((b) => jsx('option', { value: b.name, children: `${b.display_name} (${b.name})` }, b.name)),
          }),
          jsx('button', {
            type: 'button',
            className: btnClass('primary'),
            disabled: !target || busy,
            onClick: () => runEval(),
            children: busy ? 'Running Eval…' : 'Run Evaluation Gate',
          }),
        ],
      }),
      botObj
        ? jsxs('div', {
            className: 'grid grid-cols-2 gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3 text-xs md:grid-cols-4',
            children: [
              jsxs('div', { children: ['Total Calls: ', jsx('strong', { children: botObj.telemetry?.total_calls || 0 })] }),
              jsxs('div', { children: ['Total Errors: ', jsx('strong', { children: botObj.telemetry?.total_errors || 0 })] }),
              jsxs('div', {
                children: ['Consecutive Errors: ', jsx('strong', { children: botObj.telemetry?.consecutive_errors || 0 })],
              }),
              jsxs('div', {
                children: ['Breaker: ', jsx('strong', { children: botObj.telemetry?.breaker_tripped ? 'TRIPPED' : 'OK' })],
              }),
            ],
          })
        : null,
      evalRes
        ? jsxs('div', {
            className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3 text-xs',
            children: [
              jsxs('div', {
                className: 'flex items-center justify-between',
                children: [
                  jsx('span', { className: 'font-semibold', children: `Pass Rate: ${Math.round((evalRes.pass_rate || 0) * 100)}%` }),
                  jsx('span', {
                    className: badgeClass(evalRes.passed_all ? 'ok' : 'warn'),
                    children: evalRes.passed_all ? 'PASSED' : 'NEEDS TUNING',
                  }),
                ],
              }),
              ...(evalRes.results || []).map((r, i) =>
                jsxs(
                  'div',
                  {
                    className: 'flex items-center justify-between rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2',
                    children: [
                      jsx('span', { children: `${r.id || `case-${i + 1}`} (${r.category || 'typical'})` }),
                      jsx('span', { className: badgeClass(r.passed ? 'ok' : 'err'), children: r.passed ? 'PASS' : 'FAIL' }),
                    ],
                  },
                  r.id || String(i)
                )
              ),
              evalRes.soul_suggestions?.length
                ? jsxs('div', {
                    className: 'rounded border border-amber-500/40 bg-amber-500/10 p-2',
                    children: [
                      jsx('div', { className: 'font-semibold text-amber-300', children: 'SOUL.md Suggestions' }),
                      jsx('ul', {
                        className: 'list-disc pl-4 text-[11px]',
                        children: evalRes.soul_suggestions.map((s, idx) => jsx('li', { children: s }, String(idx))),
                      }),
                    ],
                  })
                : null,
            ],
          })
        : null,
    ],
  })
}

function GovernanceTab({ ctx, bots, selectedBot, setSelectedBot }) {
  const [omhList, setOmhList] = useState([])
  const [takeovers, setTakeovers] = useState([])
  const [journalEntries, setJournalEntries] = useState([])
  const [noteGoal, setNoteGoal] = useState('')
  const [noteOutcome, setNoteOutcome] = useState('')
  const [takeoverReason, setTakeoverReason] = useState('')

  const target = selectedBot || bots[0]?.name || ''

  const loadAll = useCallback(async () => {
    if (!target) return
    try {
      const [o, t, j] = await Promise.all([
        ctx.rest(`/bots/${target}/omh`),
        ctx.rest(`/bots/${target}/takeovers`),
        ctx.rest(`/bots/${target}/journal?limit=15`),
      ])
      if (o?.ok) setOmhList(o.candidates || [])
      if (t?.ok) setTakeovers(t.takeovers || [])
      if (j?.ok) setJournalEntries(j.entries || [])
    } catch (err) {
      notifyError(String(err?.message || err))
    }
  }, [ctx, target])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  async function reviewCandidate(candidateId, action) {
    const res = await ctx.rest(`/bots/${target}/omh`, {
      method: 'POST',
      body: { action, candidate_id: candidateId },
    })
    if (res?.ok) {
      notifyInfo(`OMH candidate ${action}d`)
      await loadAll()
    } else {
      notifyError(res?.error || 'OMH review failed')
    }
  }

  async function createTakeover() {
    if (!target || !takeoverReason.trim()) return
    const res = await ctx.rest(`/bots/${target}/takeover`, {
      method: 'POST',
      body: { reason: takeoverReason.trim() },
    })
    if (res?.ok) {
      setTakeoverReason('')
      notifyInfo('Takeover requested')
      await loadAll()
    } else {
      notifyError(res?.error || 'Takeover request failed')
    }
  }

  async function resolveTakeover(takeoverId) {
    if (!target || !takeoverId) return
    const res = await ctx.rest(`/bots/${target}/takeovers/${takeoverId}/resolve`, {
      method: 'POST',
      body: { resolution: 'Resolved by operator in DirtyForge Studio' },
    })
    if (res?.ok) {
      notifyInfo(`Takeover ${takeoverId} resolved`)
      await loadAll()
    } else {
      notifyError(res?.error || 'Failed to resolve takeover')
    }
  }

  async function addJournal() {
    if (!noteOutcome.trim()) return
    const res = await ctx.rest(`/bots/${target}/journal`, {
      method: 'POST',
      body: { status: 'NOTE', goal: noteGoal.trim() || 'Operator note', outcome: noteOutcome.trim() },
    })
    if (res?.ok) {
      setNoteGoal('')
      setNoteOutcome('')
      await loadAll()
    }
  }

  return jsxs('div', {
    className: 'flex flex-col gap-4',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsx('select', {
            className: inputClass() + ' max-w-xs',
            value: target,
            onChange: (e) => setSelectedBot(e.target.value),
            children:
              bots.length === 0
                ? jsx('option', { value: '', children: 'No Bots available' })
                : bots.map((b) => jsx('option', { value: b.name, children: `${b.display_name} (${b.name})` }, b.name)),
          }),
          jsx('button', { type: 'button', className: btnClass('default'), onClick: () => loadAll(), children: 'Refresh' }),
        ],
      }),
      jsxs('div', {
        className: 'grid grid-cols-1 gap-4 lg:grid-cols-2',
        children: [
          jsxs('div', {
            className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
            children: [
              jsx('div', { className: 'text-xs font-semibold', children: `OMH Memory Candidates (${omhList.length})` }),
              omhList.length === 0
                ? jsx('div', { className: 'text-[11px] text-(--ui-text-tertiary)', children: 'No pending OMH candidates.' })
                : omhList.map((c) =>
                    jsxs(
                      'div',
                      {
                        className: 'flex flex-col gap-1.5 rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-xs',
                        children: [
                          jsx('div', { children: c.fact || c.content || JSON.stringify(c) }),
                          jsxs('div', {
                            className: 'flex gap-1.5',
                            children: [
                              jsx('button', {
                                type: 'button',
                                className: btnClass('primary'),
                                onClick: () => reviewCandidate(c.id, 'approve'),
                                children: 'Approve',
                              }),
                              jsx('button', {
                                type: 'button',
                                className: btnClass('danger'),
                                onClick: () => reviewCandidate(c.id, 'reject'),
                                children: 'Reject',
                              }),
                            ],
                          }),
                        ],
                      },
                      c.id
                    )
                  ),
            ],
          }),
          jsxs('div', {
            className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
            children: [
              jsx('div', { className: 'text-xs font-semibold', children: `Human Takeovers (${takeovers.length})` }),
              jsxs('div', {
                className: 'flex gap-1.5',
                children: [
                  jsx('input', {
                    className: inputClass(),
                    placeholder: 'Reason for manual takeover…',
                    value: takeoverReason,
                    onChange: (e) => setTakeoverReason(e.target.value),
                  }),
                  jsx('button', {
                    type: 'button',
                    className: btnClass('default'),
                    disabled: !target || !takeoverReason.trim(),
                    onClick: () => void createTakeover(),
                    children: 'Request',
                  }),
                ],
              }),
              takeovers.length === 0
                ? jsx('div', { className: 'text-[11px] text-(--ui-text-tertiary)', children: 'No takeover requests.' })
                : takeovers.map((t, idx) =>
                    jsxs(
                      'div',
                      {
                        className: 'flex items-center justify-between gap-2 rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-xs',
                        children: [
                          jsxs('div', {
                            children: [
                              jsx('div', { className: 'font-medium', children: t.reason || 'Takeover requested' }),
                              jsx('div', {
                                className: 'text-[11px] text-(--ui-text-tertiary)',
                                children: `${t.status || 'pending_human'}${t.resolution ? ` — ${t.resolution}` : ''}`,
                              }),
                            ],
                          }),
                          t.status === 'pending_human' && t.id
                            ? jsx('button', {
                                type: 'button',
                                className: btnClass('primary'),
                                onClick: () => void resolveTakeover(t.id),
                                children: 'Resolve',
                              })
                            : jsx('span', { className: badgeClass('ok'), children: 'resolved' }),
                        ],
                      },
                      t.id || String(idx)
                    )
                  ),
            ],
          }),
        ],
      }),
      jsxs('div', {
        className: 'flex flex-col gap-2 rounded border border-(--ui-border) bg-(--ui-bg-secondary) p-3',
        children: [
          jsx('div', { className: 'text-xs font-semibold', children: 'Daily Work Journal' }),
          jsxs('div', {
            className: 'grid grid-cols-1 gap-2 md:grid-cols-3',
            children: [
              jsx('input', {
                className: inputClass(),
                placeholder: 'Goal',
                value: noteGoal,
                onChange: (e) => setNoteGoal(e.target.value),
              }),
              jsx('input', {
                className: inputClass(),
                placeholder: 'Outcome / operator note',
                value: noteOutcome,
                onChange: (e) => setNoteOutcome(e.target.value),
              }),
              jsx('button', {
                type: 'button',
                className: btnClass('primary'),
                disabled: !target || !noteOutcome.trim(),
                onClick: () => addJournal(),
                children: 'Append Journal Entry',
              }),
            ],
          }),
          jsx('div', {
            className: 'flex max-h-48 flex-col gap-1 overflow-auto',
            children: journalEntries.map((entry, idx) =>
              jsxs(
                'div',
                {
                  className: 'rounded border border-(--ui-border) bg-(--ui-bg-primary) p-2 text-[11px]',
                  children: [
                    jsx('span', { className: 'font-semibold', children: `[${entry.status || 'NOTE'}] ` }),
                    jsx('span', { children: `${entry.goal || ''} — ${entry.outcome || ''}` }),
                  ],
                },
                String(idx)
              )
            ),
          }),
        ],
      }),
    ],
  })
}

function DirtyForgePage({ ctx }) {
  const [tab, setTab] = useState('roster')
  const [bots, setBots] = useState([])
  const [selectedBot, setSelectedBot] = useState('')

  const refreshBots = useCallback(async () => {
    try {
      const res = await ctx.rest('/bots?include_hidden=true')
      if (res?.ok) setBots(res.bots || [])
    } catch (err) {
      notifyError(String(err?.message || err))
    }
  }, [ctx])

  useEffect(() => {
    void refreshBots()
  }, [refreshBots])

  return jsxs('div', {
    className: 'flex h-full flex-col gap-4 overflow-auto p-4 text-(--ui-text-primary)',
    children: [
      jsxs('div', {
        className: 'flex flex-wrap items-center justify-between gap-2 border-b border-(--ui-border) pb-3',
        children: [
          jsxs('div', {
            children: [
              jsx('h1', { className: 'text-base font-semibold', children: 'DirtyForge — Bot & Team Studio' }),
              jsx('p', {
                className: 'text-xs text-(--ui-text-tertiary)',
                children: 'Discovery interview, 279 blueprints, SOUL.md compiler, sentinel guardrails, evals & governance',
              }),
            ],
          }),
          jsxs('div', {
            className: 'flex flex-wrap gap-1.5',
            children: TABS.map((t) =>
              jsx(
                'button',
                {
                  type: 'button',
                  className: btnClass(tab === t.id ? 'primary' : 'default'),
                  onClick: () => setTab(t.id),
                  children: t.label,
                },
                t.id
              )
            ),
          }),
        ],
      }),
      tab === 'roster'
        ? jsx(RosterTab, {
            ctx,
            bots,
            onRefresh: refreshBots,
            onSelectBot: (name, nextTab) => {
              setSelectedBot(name)
              setTab(nextTab)
            },
          })
        : null,
      tab === 'interview'
        ? jsx(InterviewForgeTab, {
            ctx,
            onCreated: async (profileId) => {
              await refreshBots()
              if (profileId) setSelectedBot(profileId)
              setTab('roster')
            },
          })
        : null,
      tab === 'evals' ? jsx(EvalsTab, { ctx, bots, selectedBot, setSelectedBot }) : null,
      tab === 'governance' ? jsx(GovernanceTab, { ctx, bots, selectedBot, setSelectedBot }) : null,
    ],
  })
}

function DirtyForgeSettings({ ctx }) {
  const [settings, setSettings] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const res = await ctx.rest('/settings')
        if (active && res?.ok) setSettings(res.settings || {})
      } catch (err) {
        notifyError(String(err?.message || err))
      }
    })()
    return () => {
      active = false
    }
  }, [ctx])

  async function savePatch(patch, label) {
    if (!settings) return
    setSaving(true)
    try {
      const next = { ...settings, ...patch }
      const res = await ctx.rest('/settings', { method: 'PUT', body: { settings: next } })
      if (res?.ok) {
        setSettings(res.settings)
        notifyInfo(`Updated ${label}`)
      } else if (res?.error) {
        notifyError(res.error)
      }
    } catch (err) {
      notifyError(String(err?.message || err))
    } finally {
      setSaving(false)
    }
  }

  if (!settings) {
    return jsx('div', { className: 'p-3 text-xs text-(--ui-text-tertiary)', children: 'Loading DirtyForge settings…' })
  }

  const boolKeys = [
    ['strict_intake', 'Require completed discovery interview (strict_intake) before create_bot'],
    ['enforce_approvals', 'Install dirty-forge-sentinel (pre_tool_call guardrails & circuit breaker)'],
    ['inherit_model', 'Inherit launching profile model when no explicit model is supplied'],
    ['journal_enabled', 'Give new Bots an append-only daily work journal'],
    ['workspace_survey', 'Perform shallow read-only workspace survey into MEMORY.md'],
    ['ack_reactions', 'Prefix Bot replies with status emoji'],
    ['ack_tapback', 'Show desktop message tapback reactions during turns'],
    ['backup_before_delete', 'Export .tar.gz backup before deleting a Bot'],
    ['allow_trusted_mcp', 'Allow Bots to mark mcp_servers as trust=trusted without per-spec override'],
    ['allow_external_delegation', 'Allow delegate_outside to invoke allowlisted external CLIs'],
    ['allow_delete', 'Allow permanent Bot deletion (creates .tar.gz backup)'],
  ]

  return jsxs('div', {
    className: 'flex flex-col gap-3 p-2 text-xs',
    children: [
      jsx('div', { className: 'text-sm font-semibold', children: 'DirtyForge Settings' }),
      jsxs('div', {
        className: 'grid grid-cols-1 gap-2 rounded border border-(--ui-border) p-2.5 md:grid-cols-3',
        children: [
          jsxs('label', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('span', { className: 'text-[11px] text-(--ui-text-tertiary)', children: 'Default OMH Memory Mode' }),
              jsx('select', {
                className: inputClass(),
                value: settings.omh_memory_mode || 'auto-safe',
                disabled: saving,
                onChange: (e) => void savePatch({ omh_memory_mode: e.target.value }, 'omh_memory_mode'),
                children: [
                  jsx('option', { value: 'auto-safe', children: 'auto-safe' }, 'auto-safe'),
                  jsx('option', { value: 'review-first', children: 'review-first' }, 'review-first'),
                  jsx('option', { value: 'off', children: 'off' }, 'off'),
                ],
              }),
            ],
          }),
          jsxs('label', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('span', { className: 'text-[11px] text-(--ui-text-tertiary)', children: 'Circuit Breaker Max Calls' }),
              jsx('input', {
                type: 'number',
                min: 1,
                max: 10000,
                className: inputClass(),
                value: settings.circuit_breaker_max_calls ?? 40,
                disabled: saving,
                onChange: (e) => {
                  const n = Number.parseInt(e.target.value, 10)
                  if (Number.isFinite(n) && n >= 1) void savePatch({ circuit_breaker_max_calls: n }, 'circuit_breaker_max_calls')
                },
              }),
            ],
          }),
          jsxs('label', {
            className: 'flex flex-col gap-1',
            children: [
              jsx('span', { className: 'text-[11px] text-(--ui-text-tertiary)', children: 'Circuit Breaker Max Errors' }),
              jsx('input', {
                type: 'number',
                min: 1,
                max: 10000,
                className: inputClass(),
                value: settings.circuit_breaker_max_errors ?? 5,
                disabled: saving,
                onChange: (e) => {
                  const n = Number.parseInt(e.target.value, 10)
                  if (Number.isFinite(n) && n >= 1) void savePatch({ circuit_breaker_max_errors: n }, 'circuit_breaker_max_errors')
                },
              }),
            ],
          }),
        ],
      }),
      boolKeys.map(([key, label]) =>
        jsxs(
          'label',
          {
            className: 'flex items-center justify-between gap-3 rounded border border-(--ui-border) p-2.5 cursor-pointer',
            children: [
              jsx('span', { children: label }),
              jsx('input', {
                type: 'checkbox',
                checked: Boolean(settings[key]),
                disabled: saving,
                onChange: () => void savePatch({ [key]: !settings[key] }, key),
              }),
            ],
          },
          key
        )
      ),
    ],
  })
}

export default {
  id: 'dirty-forge',
  name: 'DirtyForge',
  register(ctx) {
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/dirty-forge' },
        render: () => jsx(DirtyForgePage, { ctx }),
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/dirty-forge', label: 'DirtyForge', codicon: 'hubot' },
      },
      {
        id: 'status',
        area: STATUSBAR_AREAS.right,
        order: 125,
        render: () => jsx(DirtyForgeStatusChip, { ctx }),
      },
      {
        id: 'cmd-open',
        area: PALETTE_AREA,
        data: {
          id: 'dirty-forge.open',
          label: 'Open DirtyForge Studio',
          keywords: ['dirty', 'forge', 'bot', 'agent'],
          run: () => host.navigate('/dirty-forge'),
        },
      },
      {
        id: 'cmd-sync',
        area: PALETTE_AREA,
        data: {
          id: 'dirty-forge.sync-policies',
          label: 'DirtyForge: Sync Bot Policies',
          keywords: ['dirty', 'forge', 'policy', 'sync'],
          run: async () => {
            try {
              await ctx.rest('/policies/sync', { method: 'POST' })
              notifyInfo('DirtyForge policies synced')
            } catch (err) {
              notifyError(String(err?.message || err))
            }
          },
        },
      },
    ])

    ctx.registerSettingsPage?.({
      id: 'settings',
      title: 'DirtyForge',
      icon: 'hubot',
      order: 20,
      render: () => jsx(DirtyForgeSettings, { ctx }),
    })
  },
}
