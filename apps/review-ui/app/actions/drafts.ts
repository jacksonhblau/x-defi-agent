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
  const { error } = await db
    .from('drafts')
    .update({
      edited_body: editedBody,
      status: 'edited',
      reviewed_at: new Date().toISOString(),
    })
    .eq('id', id)
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
