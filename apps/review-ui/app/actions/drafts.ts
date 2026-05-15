'use server'

import { createServerClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'

export async function approveDraft(id: string) {
  const db = createServerClient()
  const { error } = await db
    .from('drafts')
    .update({ status: 'approved', reviewed_at: new Date().toISOString() })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/drafts')
}

export async function rejectDraft(id: string) {
  const db = createServerClient()
  const { error } = await db
    .from('drafts')
    .update({ status: 'rejected', reviewed_at: new Date().toISOString() })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/drafts')
}

export async function editDraft(id: string, editedBody: string) {
  const db = createServerClient()

  // First fetch the draft so we know its format. For threads, the poster reads
  // body_json (an array of per-tweet strings) — NOT edited_body. So we have to
  // re-split the edited text on blank lines and overwrite body_json. Otherwise
  // the edit silently dies and the original wording posts.
  const { data: draft, error: fetchErr } = await db
    .from('drafts')
    .select('format')
    .eq('id', id)
    .single()
  if (fetchErr) throw new Error(fetchErr.message)

  // Split on one-or-more blank lines (handle \r\n too).
  const tweets = editedBody
    .split(/\r?\n\s*\r?\n+/)
    .map((s) => s.trim())
    .filter(Boolean)

  const update: Record<string, unknown> = {
    edited_body: editedBody,
    status: 'edited',
    reviewed_at: new Date().toISOString(),
  }
  if (draft?.format === 'thread') {
    update.body_json = tweets
  }

  const { error } = await db.from('drafts').update(update).eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/drafts')
}

export async function bulkApproveDrafts(ids: string[]) {
  if (!ids.length) return
  const db = createServerClient()
  const { error } = await db
    .from('drafts')
    .update({ status: 'approved', reviewed_at: new Date().toISOString() })
    .in('id', ids)
  if (error) throw new Error(error.message)
  revalidatePath('/drafts')
}

export async function bulkRejectDrafts(ids: string[]) {
  if (!ids.length) return
  const db = createServerClient()
  const { error } = await db
    .from('drafts')
    .update({ status: 'rejected', reviewed_at: new Date().toISOString() })
    .in('id', ids)
  if (error) throw new Error(error.message)
  revalidatePath('/drafts')
}
