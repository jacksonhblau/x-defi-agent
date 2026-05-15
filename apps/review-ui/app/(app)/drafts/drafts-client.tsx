'use client'

import { useState, useTransition, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { CheckCircle, XCircle, AlertTriangle, Edit2, ChevronUp, ChevronDown, Search } from 'lucide-react'
import { cn, truncate, relativeTime } from '@/lib/utils'
import type { Draft, DraftFormat, DraftStatus } from '@/lib/types'
import { StatusBadge } from '@/components/status-badge'
import { FormatBadge } from '@/components/format-badge'
import { RelativeTime } from '@/components/relative-time'
import { BodyDrawer } from '@/components/body-drawer'
import { Topbar } from '@/components/topbar'
import { useToast } from '@/components/toast'
import {
  approveDraft,
  rejectDraft,
  editDraft,
  bulkApproveDrafts,
  bulkRejectDrafts,
} from '@/app/actions/drafts'

type SortKey = 'created_at' | 'format' | 'status'
type SortDir = 'asc' | 'desc'

const FORMATS: DraftFormat[] = ['single', 'thread', 'reply', 'quote_tweet', 'hot_take']
const STATUSES: DraftStatus[] = ['pending', 'approved', 'edited']

interface DraftsClientProps {
  initialDrafts: Draft[]
  counts: { pending: number; approved: number; posted: number }
}

export function DraftsClient({ initialDrafts, counts }: DraftsClientProps) {
  const router = useRouter()
  const { toast } = useToast()
  const [isPending, startTransition] = useTransition()

  // Filters
  const [search, setSearch] = useState('')
  const [formatFilter, setFormatFilter] = useState<Set<DraftFormat>>(new Set())
  const [statusFilter, setStatusFilter] = useState<Set<DraftStatus>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Drawer
  const [drawerDraft, setDrawerDraft] = useState<Draft | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // Edit modal
  const [editingDraft, setEditingDraft] = useState<Draft | null>(null)
  const [editBody, setEditBody] = useState('')
  const [editLoading, setEditLoading] = useState(false)

  // Filtered + sorted drafts
  const drafts = useMemo(() => {
    let list = [...initialDrafts]
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(
        (d) =>
          d.body.toLowerCase().includes(q) ||
          d.stories?.headline?.toLowerCase().includes(q) ||
          (d.edited_body ?? '').toLowerCase().includes(q)
      )
    }
    if (formatFilter.size) list = list.filter((d) => formatFilter.has(d.format))
    if (statusFilter.size) list = list.filter((d) => statusFilter.has(d.status))
    list.sort((a, b) => {
      let va = a[sortKey] ?? ''
      let vb = b[sortKey] ?? ''
      if (typeof va === 'string' && typeof vb === 'string') {
        return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
      }
      return 0
    })
    return list
  }, [initialDrafts, search, formatFilter, statusFilter, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <ChevronUp size={12} className="opacity-20" />
    return sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
  }

  function toggleFormat(f: DraftFormat) {
    setFormatFilter((prev) => {
      const next = new Set(prev)
      next.has(f) ? next.delete(f) : next.add(f)
      return next
    })
  }

  function toggleStatus(s: DraftStatus) {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (selected.size === drafts.length) setSelected(new Set())
    else setSelected(new Set(drafts.map((d) => d.id)))
  }

  function openDrawer(draft: Draft) {
    setDrawerDraft(draft)
    setDrawerOpen(true)
  }

  function openEdit(draft: Draft) {
    setEditingDraft(draft)
    setEditBody(draft.edited_body || draft.body)
  }

  async function handleApprove(id: string) {
    startTransition(async () => {
      try {
        await approveDraft(id)
        toast('Draft approved. Worker will schedule within 60 seconds.', 'success')
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleReject(id: string) {
    startTransition(async () => {
      try {
        await rejectDraft(id)
        toast('Draft rejected.', 'info')
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleBulkApprove() {
    startTransition(async () => {
      try {
        await bulkApproveDrafts(Array.from(selected))
        toast(`${selected.size} drafts approved.`, 'success')
        setSelected(new Set())
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleBulkReject() {
    startTransition(async () => {
      try {
        await bulkRejectDrafts(Array.from(selected))
        toast(`${selected.size} drafts rejected.`, 'info')
        setSelected(new Set())
        router.refresh()
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  async function handleSaveEdit() {
    if (!editingDraft) return
    setEditLoading(true)
    try {
      await editDraft(editingDraft.id, editBody)
      toast('Draft saved as edited.', 'success')
      setEditingDraft(null)
      router.refresh()
    } catch (e) {
      toast((e as Error).message, 'error')
    }
    setEditLoading(false)
  }

  return (
    <>
      <Topbar title="Drafts" onRefresh={() => router.refresh()} isRefreshing={isPending} />

      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Header bar */}
        <div className="px-4 py-3 border-b border-border bg-background flex flex-col gap-2.5">
          {/* Counts row */}
          <div className="flex items-center gap-4 text-xs text-muted">
            <span>
              <span className="font-semibold text-foreground tabular-nums">{counts.pending}</span> pending
            </span>
            <span>
              <span className="font-semibold text-foreground tabular-nums">{counts.approved}</span> approved waiting to post
            </span>
            <span>
              <span className="font-semibold text-foreground tabular-nums">{counts.posted}</span> posted lifetime
            </span>
            {selected.size > 0 && (
              <span className="ml-auto flex items-center gap-2">
                <span className="font-semibold text-foreground">{selected.size} selected</span>
                <button
                  onClick={handleBulkApprove}
                  disabled={isPending}
                  className="px-2.5 h-6 text-xs font-medium rounded bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  Approve all
                </button>
                <button
                  onClick={handleBulkReject}
                  disabled={isPending}
                  className="px-2.5 h-6 text-xs font-medium rounded border border-danger text-danger hover:bg-[#fef2f2] disabled:opacity-50 transition-colors"
                >
                  Reject all
                </button>
              </span>
            )}
          </div>

          {/* Filters row */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Search */}
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Search body…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 pr-3 h-7 text-xs border border-border rounded bg-background text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent/40 focus:border-accent w-48"
              />
            </div>
            <div className="h-4 w-px bg-border" />
            {/* Format chips */}
            {FORMATS.map((f) => (
              <button
                key={f}
                onClick={() => toggleFormat(f)}
                className={cn(
                  'h-6 px-2.5 text-xs rounded border transition-colors',
                  formatFilter.has(f)
                    ? 'border-accent bg-accent/10 text-accent font-medium'
                    : 'border-border text-muted hover:border-foreground/30 hover:text-foreground'
                )}
              >
                {f === 'quote_tweet' ? 'QT' : f.replace('_', ' ')}
              </button>
            ))}
            <div className="h-4 w-px bg-border" />
            {/* Status chips */}
            {STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                className={cn(
                  'h-6 px-2.5 text-xs rounded border transition-colors',
                  statusFilter.has(s)
                    ? 'border-accent bg-accent/10 text-accent font-medium'
                    : 'border-border text-muted hover:border-foreground/30 hover:text-foreground'
                )}
              >
                {s}
              </button>
            ))}
            {(formatFilter.size > 0 || statusFilter.size > 0 || search) && (
              <button
                onClick={() => { setFormatFilter(new Set()); setStatusFilter(new Set()); setSearch('') }}
                className="h-6 px-2 text-xs text-danger hover:underline"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          {drafts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
              <CheckCircle size={36} className="text-success opacity-40" />
              <p className="text-sm font-medium text-foreground">Inbox zero</p>
              <p className="text-xs text-muted max-w-xs">
                The worker will surface new drafts as they are generated.
              </p>
            </div>
          ) : (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="sticky top-0 z-10 bg-surface border-b border-border">
                  <th className="w-8 px-3 py-2 text-left">
                    <input
                      type="checkbox"
                      checked={selected.size === drafts.length && drafts.length > 0}
                      onChange={toggleAll}
                      className="cursor-pointer accent-accent"
                    />
                  </th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-24">
                    <button onClick={() => toggleSort('format')} className="flex items-center gap-1 hover:text-foreground">
                      Format <SortIcon col="format" />
                    </button>
                  </th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-56">Headline</th>
                  <th className="px-3 py-2 text-left font-medium text-muted">Body</th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-16">AI</th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-24">
                    <button onClick={() => toggleSort('status')} className="flex items-center gap-1 hover:text-foreground">
                      Status <SortIcon col="status" />
                    </button>
                  </th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-28">
                    <button onClick={() => toggleSort('created_at')} className="flex items-center gap-1 hover:text-foreground">
                      Created <SortIcon col="created_at" />
                    </button>
                  </th>
                  <th className="px-3 py-2 text-left font-medium text-muted w-44">Actions</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((draft, idx) => (
                  <tr
                    key={draft.id}
                    className={cn(
                      'border-b border-border h-10 group',
                      idx % 2 === 1 ? 'bg-surface/50' : 'bg-background',
                      'hover:bg-accent/5 transition-colors'
                    )}
                  >
                    <td className="px-3">
                      <input
                        type="checkbox"
                        checked={selected.has(draft.id)}
                        onChange={() => toggleSelect(draft.id)}
                        className="cursor-pointer accent-accent"
                      />
                    </td>
                    <td className="px-3">
                      <FormatBadge format={draft.format} />
                    </td>
                    <td className="px-3 text-foreground">
                      <span className="line-clamp-2 leading-4" title={draft.stories?.headline ?? ''}>
                        {truncate(draft.stories?.headline ?? null, 60)}
                      </span>
                    </td>
                    <td className="px-3">
                      <button
                        onClick={() => openDrawer(draft)}
                        className="text-left text-muted hover:text-accent transition-colors line-clamp-2 leading-4"
                        title="Click to expand"
                      >
                        {truncate(draft.edited_body || draft.body, 100)}
                      </button>
                    </td>
                    <td className="px-3">
                      {draft.ai_check_passed === true ? (
                        <CheckCircle size={14} className="text-success" />
                      ) : draft.ai_check_passed === false ? (
                        <span
                          title={(draft.ai_check_flags ?? []).join('\n')}
                          className="cursor-help"
                        >
                          <AlertTriangle size={14} className="text-danger" />
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-3">
                      <StatusBadge status={draft.status} />
                    </td>
                    <td className="px-3 text-muted tabular-nums">
                      <RelativeTime dateStr={draft.created_at} />
                    </td>
                    <td className="px-3">
                      <div className="flex items-center gap-1">
                        {draft.status !== 'approved' && (
                          <button
                            onClick={() => handleApprove(draft.id)}
                            disabled={isPending}
                            className="px-2.5 h-6 text-xs font-medium rounded bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
                          >
                            Approve
                          </button>
                        )}
                        <button
                          onClick={() => openEdit(draft)}
                          className="p-1.5 rounded text-muted hover:text-foreground hover:bg-border/60 transition-colors"
                          title="Edit"
                        >
                          <Edit2 size={12} />
                        </button>
                        <button
                          onClick={() => handleReject(draft.id)}
                          disabled={isPending}
                          className="p-1.5 rounded text-muted hover:text-danger hover:bg-[#fef2f2] disabled:opacity-50 transition-colors"
                          title="Reject"
                        >
                          <XCircle size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination footer */}
        {drafts.length > 0 && (
          <div className="px-4 py-2 border-t border-border bg-surface flex items-center justify-between text-xs text-muted shrink-0">
            <span>Showing <span className="tabular-nums font-medium text-foreground">{drafts.length}</span> drafts</span>
          </div>
        )}
      </div>

      {/* Body Drawer */}
      <BodyDrawer
        draft={drawerDraft}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onApprove={handleApprove}
        onReject={handleReject}
        onEdit={openEdit}
      />

      {/* Edit Modal */}
      {editingDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-background border border-border rounded-lg w-[640px] max-w-full mx-4 flex flex-col shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <p className="text-sm font-semibold text-foreground">Edit draft</p>
              <button onClick={() => setEditingDraft(null)} className="text-muted hover:text-foreground">
                ✕
              </button>
            </div>
            <div className="p-4">
              <textarea
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
                rows={10}
                className="w-full text-sm border border-border rounded p-3 text-foreground bg-background focus:outline-none focus:ring-1 focus:ring-accent/40 resize-y font-mono leading-relaxed"
              />
              <p className="text-xs text-muted mt-1">
                {editBody.length} chars{editingDraft.format === 'single' && editBody.length > 280 && (
                  <span className="text-warning ml-2">Over 280 chars</span>
                )}
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-border">
              <button
                onClick={() => setEditingDraft(null)}
                className="px-3 h-8 text-sm border border-border rounded text-foreground hover:bg-surface transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={editLoading || !editBody.trim()}
                className="px-3 h-8 text-sm font-medium rounded bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {editLoading ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
