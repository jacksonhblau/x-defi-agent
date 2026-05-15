'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Play } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { RunJob } from '@/lib/types'
import { StatusBadge } from '@/components/status-badge'
import { RelativeTime } from '@/components/relative-time'
import { Topbar } from '@/components/topbar'
import { useToast } from '@/components/toast'
import { updateJobCron, toggleJobEnabled, triggerRunNow } from '@/app/actions/jobs'

// Infer category from job name
function category(name: string): string {
  if (/ingest/.test(name)) return 'Ingest'
  if (/score|build_stories|draft/.test(name)) return 'Processing'
  if (/hot_take|weekly|recap/.test(name)) return 'Scheduled'
  if (/post|engagement/.test(name)) return 'Output'
  return 'Other'
}

interface JobsClientProps {
  initialJobs: RunJob[]
}

export function JobsClient({ initialJobs }: JobsClientProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [isPending, startTransition] = useTransition()
  const [editingCron, setEditingCron] = useState<Record<string, string>>({})

  const grouped = initialJobs.reduce<Record<string, RunJob[]>>((acc, job) => {
    const cat = category(job.name)
    ;(acc[cat] = acc[cat] ?? []).push(job)
    return acc
  }, {})

  async function handleToggle(job: RunJob) {
    startTransition(async () => {
      try {
        await toggleJobEnabled(job.id, !job.enabled)
        toast(`${job.name} ${job.enabled ? 'disabled' : 'enabled'}.`, 'info')
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleSaveCron(job: RunJob) {
    const cron = editingCron[job.id]
    if (cron === undefined) return
    startTransition(async () => {
      try {
        await updateJobCron(job.id, cron || null)
        toast(`Cron updated for ${job.name}.`, 'success')
        setEditingCron((prev) => { const n = { ...prev }; delete n[job.id]; return n })
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleRunNow(job: RunJob) {
    startTransition(async () => {
      try {
        await triggerRunNow(job.id)
        toast(`${job.name} will run on the next worker cycle (~60s).`, 'info')
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  return (
    <>
      <Topbar title="Run Jobs" onRefresh={() => router.refresh()} isRefreshing={isPending} />
      <div className="flex-1 overflow-auto px-4 py-4 flex flex-col gap-6">
        {Object.entries(grouped).map(([cat, jobs]) => (
          <div key={cat}>
            <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">{cat}</h2>
            <div className="border border-border rounded overflow-hidden">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-surface border-b border-border">
                    <th className="px-3 py-2 text-left font-medium text-muted w-44">Name</th>
                    <th className="px-3 py-2 text-left font-medium text-muted">Description</th>
                    <th className="px-3 py-2 text-left font-medium text-muted w-40">Cron</th>
                    <th className="px-3 py-2 text-left font-medium text-muted w-16">On</th>
                    <th className="px-3 py-2 text-left font-medium text-muted w-28">Last run</th>
                    <th className="px-3 py-2 text-left font-medium text-muted w-24">Status</th>
                    <th className="px-3 py-2 text-left font-medium text-muted w-24">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job, idx) => (
                    <tr
                      key={job.id}
                      className={cn(
                        'border-b border-border last:border-0 h-10',
                        idx % 2 === 1 ? 'bg-surface/40' : 'bg-background'
                      )}
                    >
                      <td className="px-3 font-medium text-foreground font-mono">{job.name}</td>
                      <td className="px-3 text-muted">{job.description ?? '—'}</td>
                      <td className="px-3">
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={editingCron[job.id] !== undefined ? editingCron[job.id] : (job.cron ?? '')}
                            onChange={(e) => setEditingCron((p) => ({ ...p, [job.id]: e.target.value }))}
                            placeholder="*/10 * * * *"
                            className="w-32 px-1.5 h-6 border border-border rounded text-2xs font-mono bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent/40"
                          />
                          {editingCron[job.id] !== undefined && (
                            <button
                              onClick={() => handleSaveCron(job)}
                              disabled={isPending}
                              className="px-1.5 h-6 text-2xs rounded bg-accent text-white hover:opacity-90 disabled:opacity-50"
                            >
                              Save
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="px-3">
                        <button
                          role="switch"
                          aria-checked={job.enabled}
                          onClick={() => handleToggle(job)}
                          disabled={isPending}
                          className={cn(
                            'relative inline-flex h-4 w-7 items-center rounded-full transition-colors disabled:opacity-50',
                            job.enabled ? 'bg-accent' : 'bg-border'
                          )}
                        >
                          <span className={cn(
                            'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                            job.enabled ? 'translate-x-3.5' : 'translate-x-0.5'
                          )} />
                        </button>
                      </td>
                      <td className="px-3 text-muted tabular-nums">
                        {job.last_run_at ? <RelativeTime dateStr={job.last_run_at} /> : '—'}
                      </td>
                      <td className="px-3">
                        {job.last_status ? (
                          <span title={job.last_error ?? undefined}>
                            <StatusBadge status={job.last_status} />
                          </span>
                        ) : <span className="text-muted">—</span>}
                        {job.last_error && (
                          <p className="text-2xs text-danger mt-0.5 truncate max-w-[160px]" title={job.last_error}>
                            {job.last_error}
                          </p>
                        )}
                      </td>
                      <td className="px-3">
                        <button
                          onClick={() => handleRunNow(job)}
                          disabled={isPending || job.run_now}
                          title={job.run_now ? 'Queued for next cycle' : 'Run now'}
                          className={cn(
                            'flex items-center gap-1 px-2 h-6 text-2xs rounded border transition-colors disabled:opacity-50',
                            job.run_now
                              ? 'border-accent text-accent'
                              : 'border-border text-muted hover:border-foreground/30 hover:text-foreground'
                          )}
                        >
                          <Play size={10} />
                          {job.run_now ? 'Queued' : 'Run now'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
        {initialJobs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 text-center gap-2">
            <p className="text-sm font-medium text-foreground">No jobs found</p>
            <p className="text-xs text-muted">Run jobs will appear here once the worker populates the table.</p>
          </div>
        )}
      </div>
    </>
  )
}
