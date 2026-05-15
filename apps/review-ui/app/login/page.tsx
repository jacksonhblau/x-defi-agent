'use client'

import { useState } from 'react'
import { signIn } from 'next-auth/react'
import { useRouter } from 'next/navigation'
import { Eye, EyeOff, Lock } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function LoginPage() {
  const router = useRouter()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPw, setShowPw] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    const res = await signIn('credentials', {
      password,
      redirect: false,
    })
    setLoading(false)
    if (res?.ok) {
      router.replace('/drafts')
    } else {
      setError('Incorrect password.')
      setPassword('')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div
        className="w-full max-w-sm border border-border rounded-lg bg-surface p-8"
        style={{ boxShadow: '0 1px 4px 0 rgba(0,0,0,0.06)' }}
      >
        <div className="flex items-center gap-2 mb-6">
          <div className="w-7 h-7 rounded bg-accent flex items-center justify-center">
            <span className="text-white font-bold text-sm">D</span>
          </div>
          <span className="text-base font-semibold text-foreground">DeFi Agent</span>
        </div>
        <h1 className="text-lg font-semibold text-foreground mb-1">Sign in</h1>
        <p className="text-sm text-muted mb-6">Enter your password to continue.</p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="relative">
            <Lock
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
              size={14}
            />
            <input
              type={showPw ? 'text' : 'password'}
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
              className={cn(
                'w-full pl-9 pr-9 py-2 text-sm border border-border rounded bg-background text-foreground',
                'placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent transition-colors'
              )}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowPw((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-foreground"
            >
              {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <button
            type="submit"
            disabled={loading || !password}
            className={cn(
              'w-full py-2 px-4 text-sm font-medium rounded bg-accent text-white',
              'hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity'
            )}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
