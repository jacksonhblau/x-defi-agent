import { cn } from '@/lib/utils'

const formatStyles: Record<string, string> = {
  single: 'bg-[#dbeafe] text-[#1e40af]',
  thread: 'bg-[#ede9fe] text-[#5b21b6]',
  reply: 'bg-[#d1fae5] text-[#065f46]',
  quote_tweet: 'bg-[#e0e7ff] text-[#3730a3]',
  hot_take: 'bg-[#ffedd5] text-[#9a3412]',
}

interface FormatBadgeProps {
  format: string
  className?: string
}

export function FormatBadge({ format, className }: FormatBadgeProps) {
  const label = format === 'quote_tweet' ? 'QT' : format.replace('_', ' ')
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 h-5 rounded text-2xs font-medium whitespace-nowrap',
        formatStyles[format] ?? 'bg-[#f3f4f6] text-[#374151]',
        className
      )}
    >
      {label}
    </span>
  )
}
