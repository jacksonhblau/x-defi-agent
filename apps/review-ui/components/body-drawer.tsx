'use client'

import { useEffect, useRef } from 'react'
import { X, ExternalLink, AlertTriangle, CheckCircle } from 'lucide-react'
import { cn, formatET } from '@/lib/utils'
import type { Draft } from '@/lib/types'
import { StatusBadge } from './status-badge'
import { FormatBadge } from './format-badge'

interface BodyDrawerProps {
  draft: Draft | null
  open: boolean
  onClose: () => void
  onApprove?: (id: string) => void
  onReject?: (id: string) => void
  onEdit?: (draft: Draft) => void
}

export function BodyDrawer({ draft, open, onClose, onApprove, onReject, onEdit }: BodyDrawerProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    if (open) document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  if (!open || !draft) return null

  const story = draft.stories
  const body = draft.edited_body || draft.body
  const tweets = draft.body_json

  return (
    <>
      {/* Overlay */}
      <div
        ref={overlayRef}
        className="fixed inset-0 bg-black/40 z-40 transition-opacity"
        onClick={onClose}
      />
      {/* Drawer */}
      <aside className="fixed right-0 top-0 h-full w-[600px] max-w-full bg-background border-l border-border z-50 flex flex-col shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 h-12 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <FormatBadge format={draft.format} />
            <StatusBadge status={draft.status} />
          </div>
          <button
            onClick={onClose}
            className="text-muted hover:text-foreground p-1 rounded hover:bg-border/60 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
          {/* Tweet body */}
          <section>
            <p className="text-2xs font-medium text-muted uppercase tracking-wide mb-2">Body</p>
            {tweets ? (
              <div className="flex flex-col gap-2">
                {tweets.map((tweet, i) => (
                  <div key={i} className="border border-border rounded p-3 text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                    <span className="text-2xs text-muted font-medium mr-2">{i + 1}/{tweets.length}</span>
                    {tweet}
                  </div>
                ))}
              </div>
            ) : (
              <div className="border border-border rounded p-3 text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                {body}
              </div>
            )}
            {draft.edited_body && (
              <p className="text-2xs text-muted mt-1">* Showing edited version</p>
            )}
          </section>

          {/* AI check */}
          <section>
            <p className="text-2xs font-medium text-muted uppercase tracking-wide mb-2">AI Check</p>
            {draft.ai_check_passed === true ? (
              <div className="flex items-center gap-2 text-success text-sm">
                <CheckCircle size={14} />
                <span>Passed</span>
              </div>
            ) : draft.ai_check_passed === false ? (
              <div>
                <div className="flex items-center gap-2 text-danger text-sm mb-1">
                  <AlertTriangle size={14} />
                  <span>Failed</span>
                </div>
                {draft.ai_check_flags?.map((flag, i) => (
                  <p key={i} className="text-xs text-danger bg-[#fef2f2] border border-danger/20 rounded px-2 py-1 mt-1 font-mono">
                    {flag}
                  </p>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted">Not checked</span>
            )}
          </section>

          {/* Story context */}
          {story && (
            <section>
              <p className="text-2xs font-medium text-muted uppercase tracking-wide mb-2">Story</p>
              <div className="border border-border rounded p-3 flex flex-col gap-2">
                <p className="text-sm font-medium text-foreground">{story.headline}</p>
                {story.narrative_angle && (
                  <p className="text-xs text-muted italic">{story.narrative_angle}</p>
                )}
                {story.entities.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    <span className="text-2xs text-muted">Entities:</span>
                    {story.entities.map((e) => (
                      <span key={e} className="text-2xs bg-[#dbeafe] text-[#1e40af] px-1.5 py-0.5 rounded font-medium">{e}</span>
                    ))}
                  </div>
                )}
                {story.source_handles.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    <span className="text-2xs text-muted">Sources:</span>
                    {story.source_handles.map((h) => (
                      <span key={h} className="text-2xs bg-[#f3f4f6] text-[#374151] px-1.5 py-0.5 rounded font-medium">{h}</span>
                    ))}
                  </div>
                )}
                {story.key_data_points?.length > 0 && (
                  <table className="w-full text-xs border-t border-border mt-1">
                    <tbody>
                      {story.key_data_points.map((dp, i) => (
                        <tr key={i} className="border-b border-border last:border-0">
                          <td className="py-1 pr-2 text-muted font-medium w-1/3">{dp.label}</td>
                          <td className="py-1 pr-2 text-foreground tabular-nums">{dp.value}</td>
                          <td className="py-1 text-muted">{dp.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </section>
          )}

          {/* Metadata */}
          <section>
            <p className="text-2xs font-medium text-muted uppercase tracking-wide mb-2">Metadata</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <span className="text-muted">Draft ID</span>
              <span className="text-foreground font-mono truncate">{draft.id.slice(0, 8)}…</span>
              <span className="text-muted">Story ID</span>
              <span className="text-foreground font-mono truncate">{draft.story_id.slice(0, 8)}…</span>
              <span className="text-muted">Created</span>
              <span className="text-foreground">{formatET(draft.created_at)}</span>
              {draft.reviewed_at && (
                <>
                  <span className="text-muted">Reviewed</span>
                  <span className="text-foreground">{formatET(draft.reviewed_at)}</span>
                </>
              )}
              {draft.variant_label && (
                <>
                  <span className="text-muted">Variant</span>
                  <span className="text-foreground">{draft.variant_label}</span>
                </>
              )}
            </div>
          </section>
        </div>

        {/* Footer actions */}
        {(draft.status === 'pending' || draft.status === 'edited') && (
          <div className="border-t border-border px-5 py-3 flex items-center gap-2 shrink-0 bg-background">
            {onApprove && (
              <button
                onClick={() => { onApprove(draft.id); onClose() }}
                className="px-3 h-8 text-sm font-medium rounded bg-accent text-white hover:opacity-90 transition-opacity"
              >
                Approve
              </button>
            )}
            {onEdit && (
              <button
                onClick={() => { onEdit(draft); onClose() }}
                className="px-3 h-8 text-sm font-medium rounded border border-border text-foreground hover:bg-surface transition-colors"
              >
                Edit
              </button>
            )}
            {onReject && (
              <button
                onClick={() => { onReject(draft.id); onClose() }}
                className="px-3 h-8 text-sm font-medium rounded text-danger hover:bg-[#fef2f2] transition-colors"
              >
                Reject
              </button>
            )}
          </div>
        )}
      </aside>
    </>
  )
}
