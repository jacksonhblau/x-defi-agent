'use client'

import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useState, useEffect } from 'react'

interface TopbarProps {
  title: string
  onRefresh?: () => void
  isRefreshing?: boolean
}

export function Topbar({ title, onRefresh, isRefreshing }: TopbarProps) {
  const [lastRefresh, setLastRefresh] = useState(new Date())
  const [elapsed, setElapsed] = useState('just now')

  useEffect(() => {
    const tick = () => {
      const secs = Math.floor((Date.now() - lastRefresh.getTime()) / 1000)
      if (secs < 5) setElapsed('just now')
      else if (secs < 60) setElapsed(`${secs}s ago`)
      else setElapsed(`${Math.floor(secs / 60)}m ago`)
    }
    tick()
    const id = setInterval(tick, 5000)
    return () => clearInterval(id)
  }, [lastRefresh])

  function handleRefresh() {
    setLastRefresh(new Date())
    onRefresh?.()
  }

  return (
    <header className="h-12 border-b border-border bg-background flex items-center justify-between px-4 shrink-0">
      <h1 className="text-base font-semibold text-foreground">{title}</h1>
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted">Updated {elapsed}</span>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className={cn(
            'flex items-center gap-1.5 px-2.5 h-7 text-xs text-muted border border-border rounded hover:bg-surface hover:text-foreground transition-colors',
            isRefreshing && 'opacity-60'
          )}
        >
          <RefreshCw size={12} className={cn(isRefreshing && 'animate-spin')} />
          Refresh
        </button>
      </div>
    </header>
  )
}
