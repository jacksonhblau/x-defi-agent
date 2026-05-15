import { cn } from '@/lib/utils'

const statusStyles: Record<string, string> = {
  // draft statuses
  pending: 'bg-[#f3f4f6] text-[#374151]',
  approved: 'bg-[#dbeafe] text-[#1e40af]',
  rejected: 'bg-[#fee2e2] text-[#991b1b]',
  edited: 'bg-[#ede9fe] text-[#5b21b6]',
  scheduled: 'bg-[#fef3c7] text-[#92400e]',
  posted: 'bg-[#d1fae5] text-[#065f46]',
  // story statuses
  open: 'bg-[#f0f9ff] text-[#0369a1]',
  drafted: 'bg-[#ede9fe] text-[#5b21b6]',
  killed: 'bg-[#f3f4f6] text-[#9ca3af]',
  // scheduled_post statuses
  queued: 'bg-[#fef3c7] text-[#92400e]',
  posting: 'bg-[#dbeafe] text-[#1e40af]',
  failed: 'bg-[#fee2e2] text-[#991b1b]',
  // job statuses
  ok: 'bg-[#d1fae5] text-[#065f46]',
  error: 'bg-[#fee2e2] text-[#991b1b]',
  running: 'bg-[#dbeafe] text-[#1e40af]',
}

interface StatusBadgeProps {
  status: string
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 h-5 rounded text-2xs font-medium whitespace-nowrap',
        statusStyles[status] ?? 'bg-[#f3f4f6] text-[#374151]',
        className
      )}
    >
      {status}
    </span>
  )
}
