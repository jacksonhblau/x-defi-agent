# Design system

Tight visual rules so v0 produces a coherent dashboard, not a generic SaaS template.

## Reference products
- **Linear** for navigation density, keyboard shortcuts, motion
- **Stripe Dashboard** for data tables and the "operator tool" feel
- **Supabase Dashboard** for the developer-utility aesthetic

Don't reference Notion (too soft), Slack (too consumer), or generic SaaS landing-page Tailwind templates.

## Color palette

**Light mode (default):**
- Background: `#FFFFFF`
- Surface (cards, sidebar): `#FAFAFA`
- Border: `#E5E7EB`
- Text primary: `#111827`
- Text secondary: `#6B7280`
- Accent: `#1F6FEB` (primary buttons, links, focus rings)
- Success: `#10B981`
- Warning: `#F59E0B`
- Danger: `#EF4444`

**Dark mode:**
- Background: `#0A0A0A`
- Surface: `#171717`
- Border: `#2A2A2A`
- Text primary: `#F5F5F5`
- Text secondary: `#A1A1AA`
- Accent: `#3B82F6`
- Success: `#10B981`
- Warning: `#F59E0B`
- Danger: `#EF4444`

Single accent only. No purple/pink gradients. No glow effects.

## Typography
- **Font:** Inter (Google Fonts). Variable weight.
- **Sizes:** 12px (small/meta), 14px (body), 16px (headings in tables), 20px (page titles)
- **Numbers in tables:** tabular-nums (`font-variant-numeric: tabular-nums`)

## Spacing
- Compact. Table rows ~40px tall.
- 16px gutters between sections, 8px within a card.
- Don't pad data away from the viewer.

## Components

### Tables
- Sticky headers, subtle border-bottom on header
- Hover state on rows (background tint, no border change)
- Row click opens drawer; row hover does NOT change cursor unless clickable
- Sort indicators inline with column names (small chevron)
- Filter chips above the table, not as a sidebar
- Pagination at the bottom: "Showing 1-50 of 234"

### Badges (status, format, etc)
- Small (h-5), rounded-md, font-medium
- Colored background tint with darker text of same hue
- Examples:
  - `pending`: gray
  - `approved`: blue
  - `rejected`: red
  - `posted`: green
  - `failed`: red
  - `queued`: yellow
  - `posting`: blue with subtle pulse
  - `hot_take`: orange
  - format `single`: blue
  - format `thread`: purple
  - format `reply`: green
  - format `quote_tweet`: indigo

### Buttons
- Primary: solid accent background
- Secondary: subtle gray background, no border
- Destructive: red background
- Ghost: text-only, used for inline table actions
- Icon buttons: 32x32, hover background tint

### Drawer (slide-over)
- 600px wide on desktop, full-width on mobile
- Slide in from right with 200ms ease
- Background overlay at 40% opacity
- Close on click-outside or Escape key
- Header: title + close button
- Content scrolls; header sticky

### Empty states
- Centered, max 400px wide
- Small icon (Lucide, 40px, accent color)
- Short heading + 1-2 sentence subhead
- Optional CTA button

## Motion
- 200ms ease for everything
- No bouncy easings
- Subtle. The dashboard shouldn't feel performative.

## Density toggle
- Optional: a "compact" mode that reduces row height to 32px. Not required for v1.

## Don't
- ❌ Glassmorphism, blur effects, gradients
- ❌ Cards with shadows beyond a 1px border + subtle elevation
- ❌ Rounded-full pills for everything
- ❌ Hero-style page headers with illustrations
- ❌ Emoji in UI copy (except sparingly in empty states)
- ❌ Marketing-tone copy ("Welcome to your dashboard!" — no)
