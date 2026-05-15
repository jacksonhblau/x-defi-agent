'use client'

import { useState, useCallback, useRef } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import type { AppConfig } from '@/lib/types'
import { Topbar } from '@/components/topbar'
import { useToast } from '@/components/toast'
import { saveConfig } from '@/app/actions/config'

interface ConfigClientProps {
  initialConfig: AppConfig['data']
}

function NumInput({
  label,
  value,
  onChange,
  min,
  max,
  description,
}: {
  label: string
  value: number | undefined
  onChange: (v: number) => void
  min?: number
  max?: number
  description?: string
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border last:border-0">
      <div>
        <p className="text-xs font-medium text-foreground">{label}</p>
        {description && <p className="text-2xs text-muted mt-0.5">{description}</p>}
      </div>
      <input
        type="number"
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-20 px-2 h-7 text-xs text-right border border-border rounded bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent/40 tabular-nums"
      />
    </div>
  )
}

export function ConfigClient({ initialConfig }: ConfigClientProps) {
  const { toast } = useToast()
  const [config, setConfig] = useState(initialConfig)
  const [saving, setSaving] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const triggerSave = useCallback(
    (newConfig: AppConfig['data']) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(async () => {
        setSaving(true)
        try {
          await saveConfig(newConfig as Record<string, unknown>)
          toast('Settings saved.', 'success')
        } catch (e) {
          toast((e as Error).message, 'error')
        }
        setSaving(false)
      }, 500)
    },
    [toast]
  )

  function update(path: string[], value: unknown) {
    setConfig((prev) => {
      const next = JSON.parse(JSON.stringify(prev)) as AppConfig['data']
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let cursor: any = next
      for (let i = 0; i < path.length - 1; i++) {
        cursor = cursor[path[i]] = cursor[path[i]] ?? {}
      }
      cursor[path[path.length - 1]] = value
      triggerSave(next)
      return next
    })
  }

  function addWindow() {
    const windows = [...(config.posting_windows_et ?? []), { start_hour: 9, end_hour: 10 }]
    setConfig((prev) => {
      const next = { ...prev, posting_windows_et: windows }
      triggerSave(next)
      return next
    })
  }

  function removeWindow(idx: number) {
    const windows = (config.posting_windows_et ?? []).filter((_, i) => i !== idx)
    setConfig((prev) => {
      const next = { ...prev, posting_windows_et: windows }
      triggerSave(next)
      return next
    })
  }

  function updateWindow(idx: number, field: 'start_hour' | 'end_hour', val: number) {
    const windows = (config.posting_windows_et ?? []).map((w, i) =>
      i === idx ? { ...w, [field]: val } : w
    )
    setConfig((prev) => {
      const next = { ...prev, posting_windows_et: windows }
      triggerSave(next)
      return next
    })
  }

  return (
    <>
      <Topbar title="Config" isRefreshing={saving} />
      <div className="flex-1 overflow-auto px-4 py-4">
        <div className="max-w-xl flex flex-col gap-6">

          {/* Materiality */}
          <section>
            <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">Materiality</h2>
            <div className="border border-border rounded px-4 bg-surface">
              <NumInput
                label="Default threshold"
                value={config.materiality?.default_threshold}
                onChange={(v) => update(['materiality', 'default_threshold'], v)}
                min={0} max={100}
                description="Minimum materiality score to surface a signal"
              />
              <NumInput
                label="Novelty threshold"
                value={config.materiality?.novelty_threshold}
                onChange={(v) => update(['materiality', 'novelty_threshold'], v)}
                min={0} max={100}
                description="Minimum novelty score required"
              />
              <NumInput
                label="Minimum for thread"
                value={config.materiality?.minimum_for_thread}
                onChange={(v) => update(['materiality', 'minimum_for_thread'], v)}
                min={0} max={100}
                description="Min score to recommend thread format"
              />
            </div>
          </section>

          {/* Cadence */}
          <section>
            <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">Cadence</h2>
            <div className="border border-border rounded px-4 bg-surface">
              <NumInput
                label="Daily post cap"
                value={config.cadence?.daily_post_cap}
                onChange={(v) => update(['cadence', 'daily_post_cap'], v)}
                min={1}
                description="Max posts per day"
              />
              <NumInput
                label="Min minutes between posts"
                value={config.cadence?.min_minutes_between_posts}
                onChange={(v) => update(['cadence', 'min_minutes_between_posts'], v)}
                min={0}
                description="Minimum gap between consecutive posts"
              />
              <NumInput
                label="Thread max per day"
                value={config.cadence?.thread_max_per_day}
                onChange={(v) => update(['cadence', 'thread_max_per_day'], v)}
                min={0}
                description="Max thread posts per day"
              />
            </div>
          </section>

          {/* Posting windows */}
          <section>
            <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">
              Posting windows (ET hours)
            </h2>
            <div className="border border-border rounded px-4 pb-3 bg-surface">
              {(config.posting_windows_et ?? []).map((w, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 border-b border-border last:border-0">
                  <span className="text-xs text-muted w-6">{i + 1}.</span>
                  <div className="flex items-center gap-2 flex-1">
                    <input
                      type="number"
                      value={w.start_hour}
                      onChange={(e) => updateWindow(i, 'start_hour', Number(e.target.value))}
                      min={0} max={23}
                      className="w-16 px-2 h-7 text-xs border border-border rounded bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent/40 tabular-nums text-right"
                    />
                    <span className="text-xs text-muted">to</span>
                    <input
                      type="number"
                      value={w.end_hour}
                      onChange={(e) => updateWindow(i, 'end_hour', Number(e.target.value))}
                      min={0} max={23}
                      className="w-16 px-2 h-7 text-xs border border-border rounded bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent/40 tabular-nums text-right"
                    />
                    <span className="text-xs text-muted">:00 ET</span>
                  </div>
                  <button
                    onClick={() => removeWindow(i)}
                    className="text-muted hover:text-danger p-1 rounded hover:bg-[#fef2f2] transition-colors"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              <button
                onClick={addWindow}
                className="mt-2 flex items-center gap-1.5 text-xs text-accent hover:underline"
              >
                <Plus size={13} />
                Add window
              </button>
            </div>
          </section>

          {/* Onchain thresholds */}
          <section>
            <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">Onchain thresholds</h2>
            <div className="border border-border rounded px-4 bg-surface">
              <NumInput
                label="TVL delta % threshold"
                value={config.onchain?.tvl_delta_threshold_pct}
                onChange={(v) => update(['onchain', 'tvl_delta_threshold_pct'], v)}
                min={0}
                description="Minimum % TVL change to trigger a signal"
              />
              <NumInput
                label="APY shift bps threshold"
                value={config.onchain?.apy_delta_threshold_bps}
                onChange={(v) => update(['onchain', 'apy_delta_threshold_bps'], v)}
                min={0}
                description="Minimum basis-point APY change to trigger a signal"
              />
            </div>
          </section>

          {saving && (
            <p className="text-xs text-muted">Saving…</p>
          )}
        </div>
      </div>
    </>
  )
}
