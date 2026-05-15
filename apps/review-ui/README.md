# DeFi Agent Admin Dashboard

A professional Next.js application for managing and reviewing posts for the X DeFi posting agent. The dashboard provides comprehensive tools for content management, scheduling, performance monitoring, and configuration.

## Features

- **Drafts Management**: Create, edit, and approve/reject post drafts with real-time updates
- **Calendar View**: Visual timeline of scheduled and published posts
- **Performance Analytics**: Track engagement metrics (likes, retweets, replies, impressions)
- **Stories & Signals**: Monitor posted content and system signals
- **Job Management**: View and control background jobs and processing tasks
- **Configuration**: Manage system settings and thresholds
- **Watchlist**: Track specific assets and monitored tokens
- **Authentication**: Secure login with NextAuth.js

## Tech Stack

- **Framework**: Next.js 16 (App Router)
- **Styling**: Tailwind CSS 4 with custom theme system
- **Database**: Supabase PostgreSQL (optional)
- **Authentication**: NextAuth.js
- **State Management**: React hooks with Context
- **UI Components**: Custom React components with Lucide icons
- **Language**: TypeScript

## Getting Started

### Prerequisites

- Node.js 18+ (Turbopack requires Node 18.17+)
- npm, yarn, pnpm, or bun

### Installation

1. Clone the repository:
```bash
git clone https://github.com/jacksonhblau/x-defi-agent.git
cd apps/review-ui
```

2. Install dependencies:
```bash
npm install
```

3. Create `.env.local` with required variables:
```env
NEXTAUTH_SECRET=your-secret-key-change-in-production
NEXTAUTH_URL=http://localhost:3000

# Optional: Supabase integration
NEXT_PUBLIC_SUPABASE_URL=your-supabase-url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key
```

4. Start the development server:
```bash
npm run dev
```

Visit http://localhost:3000/login to access the application.

## Project Structure

```
apps/review-ui/
├── app/
│   ├── (app)/              # Protected routes with layout
│   │   ├── drafts/         # Draft management and approval
│   │   ├── calendar/       # Post scheduling calendar
│   │   ├── stories/        # Published content tracking
│   │   ├── signals/        # System signals and alerts
│   │   ├── posts/          # Performance analytics
│   │   ├── jobs/           # Background job management
│   │   ├── config/         # System configuration
│   │   └── watchlist/      # Asset watchlist
│   ├── login/              # Login page
│   ├── api/auth/           # NextAuth endpoints
│   └── layout.tsx          # Root layout
├── components/
│   ├── sidebar.tsx         # Navigation sidebar
│   ├── topbar.tsx          # Page header with actions
│   ├── status-badge.tsx    # Status indicator component
│   ├── format-badge.tsx    # Content format badge
│   ├── body-drawer.tsx     # Detail drawer for drafts
│   ├── toast.tsx           # Toast notifications
│   └── relative-time.tsx   # Relative timestamp display
├── lib/
│   ├── types.ts            # TypeScript interfaces
│   ├── utils.ts            # Utility functions
│   ├── auth.ts             # Authentication config
│   └── supabase/           # Supabase client setup
├── app/actions/            # Server actions
│   ├── drafts.ts           # Draft mutations
│   ├── jobs.ts             # Job actions
│   ├── config.ts           # Config mutations
│   └── watchlist.ts        # Watchlist actions
└── public/                 # Static assets
```

## Authentication

The dashboard uses NextAuth.js with a custom password-based login. The default password is configured via environment variables.

To customize:
1. Update `lib/auth.ts` with your authentication provider
2. Modify the login page at `app/login/page.tsx`

## Database Schema

The application expects the following database tables (see `packages/db/schema.sql`):

- `posts` - Published posts and metrics
- `drafts` - Post drafts awaiting approval
- `engagement` - Engagement metrics by time window
- `jobs` - Background job records
- `config` - System configuration

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `NEXTAUTH_SECRET` | Secret for NextAuth sessions | Yes |
| `NEXTAUTH_URL` | Application URL | Yes |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL | No |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase public key | No |

## Development

### Build for production:
```bash
npm run build
npm start
```

### Run tests (when configured):
```bash
npm test
```

### Linting:
```bash
npm run lint
```

## Deployment

### Deploy to Vercel (recommended):
1. Push code to GitHub
2. Import project in Vercel dashboard
3. Add environment variables
4. Deploy

### Manual deployment:
```bash
npm run build
npm start
```

## Color Palette

The dashboard uses a professional color system:

- **Background**: `#ffffff` (light) / `#0a0a0a` (dark)
- **Foreground**: `#111827` (text)
- **Accent**: `#1f6feb` (primary action)
- **Success**: `#10b981`
- **Warning**: `#f59e0b`
- **Danger**: `#ef4444`

## Performance Optimization

- Server-side rendering for faster initial loads
- Incremental Static Regeneration (ISR) for data
- Optimized images and assets
- Lazy loading for modals and drawers
- React Query integration ready for client-side caching

## Security

- CSRF protection via NextAuth.js
- Secure password hashing
- HTTP-only cookies for sessions
- Environment variable protection
- Input validation and sanitization

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari 14+, Chrome for Android)

## Contributing

1. Create a feature branch
2. Make changes
3. Submit a pull request
4. Ensure tests pass

## License

Proprietary - All rights reserved

## Support

For issues or questions, contact the development team or open an issue on GitHub.
