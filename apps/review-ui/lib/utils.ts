import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { formatDistanceToNow, format, parseISO } from 'date-fns'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function relativeTime(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    const date = typeof dateStr === 'string' ? parseISO(dateStr) : dateStr
    return formatDistanceToNow(date, { addSuffix: true })
  } catch {
    return '—'
  }
}

export function formatET(dateStr: string | null, fmt = 'EEE h:mm a'): string {
  if (!dateStr) return '—'
  try {
    const date = typeof dateStr === 'string' ? parseISO(dateStr) : new Date(dateStr)
    return format(date, fmt) + ' ET'
  } catch {
    return '—'
  }
}

export function formatDateET(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    const date = typeof dateStr === 'string' ? parseISO(dateStr) : new Date(dateStr)
    return format(date, 'EEE MMM d, h:mm a') + ' ET'
  } catch {
    return '—'
  }
}

export function truncate(str: string | null, len: number): string {
  if (!str) return '—'
  return str.length > len ? str.slice(0, len) + '…' : str
}

export function scoreColor(score: number | null): string {
  if (score === null) return 'text-muted'
  if (score >= 70) return 'text-success'
  if (score >= 50) return 'text-warning'
  return 'text-muted'
}

export function scoreBg(score: number | null): string {
  if (score === null) return 'bg-[#f3f4f6] text-[#6b7280]'
  if (score >= 70) return 'bg-[#d1fae5] text-[#065f46]'
  if (score >= 50) return 'bg-[#fef3c7] text-[#92400e]'
  return 'bg-[#f3f4f6] text-[#6b7280]'
}
