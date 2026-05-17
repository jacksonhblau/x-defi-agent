'use server'

import { createServerClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'

// Preferred posting windows in ET (start_hour, end_hour) — mirrors
// apps/workers-py/src/workers/scheduler.py PREFERRED_WINDOWS_ET.
const PREFERRED_WINDOWS_ET: Array<[number, number]> = [
  [9, 10],   // US wake-up + market open
  [12, 13],  // lunch scroll
  [17, 18],  // commute home
  [20, 21],  // evening, catches Asia early
]
const MIN_GAP_MINUTES = 75
const DAILY_CAP_WEEKDAY = 8
const DAILY_CAP_WEEKEND = 4

/** Returns the ET-localized hour for a UTC Date. Naive but correct for the
 *  ET timezone (US/Eastern), which is what we want. */
function etHour(utc: Date): number {
  // Use Intl.DateTimeFormat to get the hour in America/New_York
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric',
    hour12: false,
  })
  return parseInt(fmt.format(utc), 10)
}

function etDateKey(utc: Date): string {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return fmt.format(utc) // YYYY-MM-DD
}

function etDayOfWeek(utc: Date): number {
  // 0=Sun..6=Sat per JS convention. Use Intl to compute weekday in ET.
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    weekday: 'short',
  })
  const wk = fmt.format(utc)
  return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(wk)
}

function inPreferredWindow(utc: Date): boolean {
  const h = etHour(utc)
  return PREFERRED_WINDOWS_ET.some(([s, e]) => h >= s && h < e)
}

function dailyCapFor(utc: Date): number {
  const dow = etDayOfWeek(utc)
  return dow === 0 || dow === 6 ? DAILY_CAP_WEEKEND : DAILY_CAP_WEEKDAY
}

/** Find the next high-virality posting slot in UTC. Mirrors
 *  scheduler.next_optimal_slot in the Python worker. */
function nextOptimalSlot(existingUtc: Date[]): Date {
  const now = new Date()
  let candidate = new Date(now.getTime() + 15 * 60 * 1000)
  candidate.setUTCSeconds(0, 0)
  candidate.setUTCMinutes(Math.floor(candidate.getUTCMinutes() / 15) * 15)

  const maxSteps = 7 * 24 * 4 // 7 days of 15-min slots
  for (let i = 0; i < maxSteps; i++) {
    if (!inPreferredWindow(candidate)) {
      candidate = new Date(candidate.getTime() + 15 * 60 * 1000)
      continue
    }
    const tooClose = existingUtc.some(
      (t) => Math.abs(candidate.getTime() - t.getTime()) < MIN_GAP_MINUTES * 60 * 1000,
    )
    if (tooClose) {
      candidate = new Date(candidate.getTime() + 15 * 60 * 1000)
      continue
    }
    const dayKey = etDateKey(candidate)
    const sameDay = existingUtc.filter((t) => etDateKey(t) === dayKey).length
    if (sameDay >= dailyCapFor(candidate)) {
      // Jump to start of next ET day
      candidate = new Date(candidate.getTime() + 4 * 60 * 60 * 1000)
      continue
    }
    return candidate
  }
  // Fallback: 24h from now (preserves at-least-tomorrow behavior)
  return new Date(now.getTime() + 24 * 60 * 60 * 1000)
}

/** Insert a row into scheduled_posts for an approved draft. Idempotent —
 *  silently skips if a row for this draft already exists in any status. */
async function scheduleApprovedDraft(
  db: ReturnType<typeof createServerClient>,
  draftId: string,
): Promise<void> {
  // Skip if already scheduled (any status)
  const { data: existing } = await db
    .from('scheduled_posts')
    .select('id')
    .eq('draft_id', draftId)
    .limit(1)
  if (existing && existing.length > 0) return

  // Pick a slot that respects gap + daily cap vs other queued/posting rows
  const { data: queued } = await db
    .from('scheduled_posts')
    .select('post_at')
    .in('status', ['queued', 'posting'])
  const existingTimes = (queued || []).map((r: { post_at: string }) => new Date(r.post_at))
  const postAt = nextOptimalSlot(existingTimes)

  const { error: insErr } = await db
    .from('scheduled_posts')
    .insert({ draft_id: draftId, post_at: postAt.toISOString(), status: 'queued' })
  if (insErr) throw new Error(`scheduled_posts insert: ${insErr.message}`)
}

export async function approveDraft(id: string) {
  const db = createServerClient()
  const { error } = await db
    .from('drafts')
    .update({ status: 'approved', reviewed_at: new Date().toISOString() })
    .eq('id', id)
  if (error) throw new Error(error.message)
  await scheduleApprovedDraft(db, id)
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
  // Schedule each one sequentially so each pick sees the prior pick's slot
  // (otherwise we'd race and pick the same slot for multiple drafts).
  for (const id of ids) {
    await scheduleApprovedDraft(db, id)
  }
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
