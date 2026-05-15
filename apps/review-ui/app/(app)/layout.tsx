import { getServerSession } from 'next-auth'
import { redirect } from 'next/navigation'
import { authOptions } from '@/lib/auth'
import { Sidebar } from '@/components/sidebar'
import { ToastProvider } from '@/components/toast'
import { createServerClient } from '@/lib/supabase/server'

async function getSidebarCounts() {
  try {
    const db = createServerClient()
    const [pendingRes, queuedRes] = await Promise.all([
      db.from('drafts').select('id', { count: 'exact', head: true }).in('status', ['pending', 'edited']),
      db.from('scheduled_posts').select('id', { count: 'exact', head: true }).eq('status', 'queued'),
    ])
    return {
      pending: pendingRes.count ?? 0,
      queued: queuedRes.count ?? 0,
    }
  } catch {
    return { pending: 0, queued: 0 }
  }
}

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions)
  if (!session) redirect('/login')

  const counts = await getSidebarCounts()

  return (
    <ToastProvider>
      <div className="flex h-screen overflow-hidden bg-background">
        <Sidebar counts={counts} />
        <div className="flex-1 flex flex-col overflow-hidden">
          {children}
        </div>
      </div>
    </ToastProvider>
  )
}
