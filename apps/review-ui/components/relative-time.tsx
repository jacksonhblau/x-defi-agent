'use client'

import { useState, useEffect } from 'react'
import { relativeTime } from '@/lib/utils'

interface RelativeTimeProps {
  dateStr: string | null
  className?: string
}

export function RelativeTime({ dateStr, className }: RelativeTimeProps) {
  const [display, setDisplay] = useState(() => relativeTime(dateStr))

  useEffect(() => {
    setDisplay(relativeTime(dateStr))
    const interval = setInterval(() => setDisplay(relativeTime(dateStr)), 30_000)
    return () => clearInterval(interval)
  }, [dateStr])

  return (
    <span className={className} title={dateStr ?? undefined}>
      {display}
    </span>
  )
}
