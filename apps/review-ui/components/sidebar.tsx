'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { signOut } from 'next-auth/react'
import {
  FileText,
  Calendar,
  BookOpen,
  Zap,
  BarChart2,
  Terminal,
  Settings,
  List,
  LogOut,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useState } from 'react'

interface NavItem {
  href: string
  label: string
  icon: React.ElementType
  badge?: number | null
}

interface SidebarProps {
  counts?: {
    pending?: number
    queued?: number
    postsToday?: number
  }
}

export function Sidebar({ counts }: SidebarProps) {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)

  const nav: NavItem[] = [
    { href: '/drafts', label: 'Drafts', icon: FileText, badge: counts?.pending },
    { href: '/calendar', label: 'Calendar', icon: Calendar, badge: counts?.queued },
    { href: '/stories', label: 'Stories', icon: BookOpen },
    { href: '/signals', label: 'Signals', icon: Zap },
    { href: '/posts', label: 'Posts', icon: BarChart2, badge: counts?.postsToday },
    { href: '/jobs', label: 'Run Jobs', icon: Terminal },
    { href: '/config', label: 'Config', icon: Settings },
    { href: '/watchlist', label: 'Watchlist', icon: List },
  ]

  return (
    <aside
      className={cn(
        'h-screen flex flex-col border-r border-border bg-surface shrink-0 transition-all duration-200',
        collapsed ? 'w-12' : 'w-52'
      )}
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 h-12 border-b border-border">
        <div className="w-6 h-6 rounded bg-accent flex items-center justify-center shrink-0">
          <span className="text-white font-bold text-xs">D</span>
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold text-foreground truncate">DeFi Agent</span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-2 overflow-y-auto">
        {nav.map((item) => {
          const Icon = item.icon
          const active = pathname === item.href || pathname.startsWith(item.href + '/')
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-2.5 px-3 h-9 text-sm rounded mx-1 transition-colors',
                active
                  ? 'bg-accent/10 text-accent font-medium'
                  : 'text-muted hover:bg-border/60 hover:text-foreground'
              )}
            >
              <Icon size={15} className="shrink-0" />
              {!collapsed && (
                <>
                  <span className="truncate flex-1">{item.label}</span>
                  {item.badge != null && item.badge > 0 && (
                    <span className="text-2xs font-semibold bg-accent text-white rounded-full px-1.5 py-0.5 min-w-[18px] text-center tabular-nums">
                      {item.badge > 99 ? '99+' : item.badge}
                    </span>
                  )}
                </>
              )}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-border py-2">
        <button
          onClick={() => signOut({ callbackUrl: '/login' })}
          className="flex items-center gap-2.5 px-3 h-9 w-full text-sm text-muted hover:text-foreground hover:bg-border/60 rounded mx-1 transition-colors"
        >
          <LogOut size={15} className="shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="flex items-center gap-2.5 px-3 h-9 w-full text-sm text-muted hover:text-foreground hover:bg-border/60 rounded mx-1 transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          {!collapsed && <span className="text-xs">Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
