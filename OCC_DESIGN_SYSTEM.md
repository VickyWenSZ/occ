# OCC Design System

Technical reference for reproducing the opencognitivecommons.org visual language in any OCC interface (web, desktop GUI, Tauri app, etc.).

---

## Philosophy

Dark, minimal, institutionally credible. The aesthetic borrows structural motifs from CLI tools — counters, monospace labels, status indicators — but keeps body text fully readable. The goal is "serious tool built by people who know what they're doing", not cyberpunk or hacker cosplay.

Rules:
- Body text is always `sans-serif`, readable, never green.
- Monospace is for data, labels, counters, hashes, code, terminal output — not prose.
- Green (`#22c55e`) is an accent only: logo, APPROVED state, live indicators, focus ring, cursor. Never for paragraphs.
- All interactive states use border/background shifts, never color explosions.
- Motion is subtle and purposeful. No decorative animations.

---

## Color Palette

All exact hex values. No opacity shortcuts — use the explicit values.

### Backgrounds & surfaces

| Token | Hex | Usage |
|-------|-----|-------|
| `bg` | `#09090b` | Page background, deepest layer |
| `surface` | `#111113` | Cards, panels, code blocks |
| `surface-hover` | `#18181b` | Hover state of surfaces, input bg |
| `surface-raised` | `#1c1c1f` | Modals, dropdowns, elevated panels |

### Borders

| Token | Hex | Usage |
|-------|-----|-------|
| `border` | `#27272a` | Default border on all elements |
| `border-subtle` | `#3f3f46` | Slightly more visible, table header bottom |
| `border-active` | `#52525b` | Focused/hovered borders |

### Text

| Token | Hex | Usage |
|-------|-----|-------|
| `text` | `#f4f4f5` | Primary text, headings |
| `text-body` | `#d4d4d8` | Long-form prose body |
| `text-muted` | `#a1a1aa` | Secondary labels, meta info |
| `text-faint` | `#71717a` | Table headers, disabled states |
| `text-ghost` | `#52525b` | Placeholder, decorative mono labels |

### Accent — Green (use sparingly)

| Token | Hex | Usage |
|-------|-----|-------|
| `green` | `#22c55e` | Logo, APPROVED badge, focus ring, cursor, live dot |
| `green-dim` | `#16a34a` | Green border on APPROVED surfaces |
| `green-bg` | `#052e16` | APPROVED badge background (very dark green) |
| `green-border` | `#166534` | APPROVED badge border |
| `green-glow` | `#22c55e30` | Selection highlight (30 = ~19% opacity) |

### Status colors

| State | Text | Background | Border |
|-------|------|------------|--------|
| APPROVED | `#4ade80` (green-400) | `#052e16` (green-950) | `#166534` (green-800) |
| UNDER_REVIEW | `#fbbf24` (amber-400) | `#1c0a00` (amber-950) | `#92400e` (amber-800) |
| CHANGES_REQUESTED | `#fb923c` (orange-400) | `#1a0a00` (orange-950) | `#9a3412` (orange-800) |
| DISPUTED | `#fb923c` (orange-400) | `#1a0a00` (orange-950) | `#9a3412` (orange-800) |
| CANDIDATE | `#d4d4d8` (zinc-300) | `#18181b` (zinc-800) | `#52525b` (zinc-600) |
| DRAFT | `#a1a1aa` (zinc-400) | `#18181b` (zinc-800) | `#3f3f46` (zinc-700) |
| DEPRECATED | `#71717a` (zinc-500) | `#09090b` (zinc-900) | `#3f3f46` (zinc-700) |
| REVOKED | `#f87171` (red-400) | `#1a0000` (red-950) | `#991b1b` (red-800) |

### Semantic colors (non-status)

| Token | Hex | Usage |
|-------|-----|-------|
| `blue` | `#38bdf8` | Links in prose, info states |
| `blue-hover` | `#7dd3fc` | Link hover |
| `amber` | `#f59e0b` | Warnings |
| `red` | `#ef4444` | Errors, destructive actions |
| `orange` | `#f97316` | Alerts |

---

## Typography

### Font stack

```
Sans:  Geist, system-ui, -apple-system, sans-serif
Mono:  Geist Mono, ui-monospace, SFMono-Regular, monospace
```

For Tauri/Electron/web without Next.js font loading, fall back to:
```
Sans:  Inter, system-ui, sans-serif
Mono:  JetBrains Mono, Fira Code, ui-monospace, monospace
```

Enable antialiasing: `-webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale`

### Type scale

| Role | Size | Weight | Font | Color |
|------|------|--------|------|-------|
| Page title (h1) | 1.875rem / 30px | 600 | sans | `#f4f4f5` |
| Section title (h2) | 1.25rem / 20px | 600 | sans | `#f4f4f5` |
| Subsection (h3) | 1rem / 16px | 600 | sans | `#f4f4f5` |
| Body | 0.875rem / 14px | 400 | sans | `#d4d4d8` |
| Body large | 1rem / 16px | 400 | sans | `#a1a1aa` |
| Label / meta | 0.75rem / 12px | 500 | mono | `#71717a` |
| Section counter | 0.75rem / 12px | 400 | mono | `#52525b` |
| Badge text | 0.625rem / 10px | 600 | mono | varies |
| Code inline | 0.875em | 400 | mono | `#22c55e` |
| Terminal output | 0.875rem / 14px | 400 | mono | `#a1a1aa` |

### Section counter pattern

Used to divide major sections. Always mono, uppercase, faint:

```
font: mono  |  size: 0.75rem  |  color: #52525b  |  letter-spacing: 0.1em  |  uppercase
```

Example: `01 / architecture` or `occ / packs / new`

---

## Surfaces & Elevation

Three levels, no shadows — elevation is expressed through border + background only.

| Level | Background | Border | Usage |
|-------|------------|--------|-------|
| 0 — page | `#09090b` | — | Root background |
| 1 — panel | `#111113` | `1px solid #27272a` | Cards, sidebars, code blocks |
| 2 — raised | `#18181b` | `1px solid #27272a` | Hover state, input fields, nested panels |
| 3 — overlay | `#1c1c1f` | `1px solid #3f3f46` | Modals, dropdowns, tooltips |

Border radius: `rounded-lg` = 8px for panels/cards, `rounded-md` = 6px for buttons/inputs/badges.

---

## Interactive States

### Hover (surfaces)
- Background: step up one elevation level (`#111113` → `#18181b`)
- Border: `#27272a` → `#3f3f46`
- Transition: `150ms ease` on `background-color`, `border-color`, `color`

### Focus
- Outline: `2px solid #22c55e`, offset `2px`
- No custom box-shadow, no glow

### Disabled
- Opacity: `0.4`
- Cursor: `not-allowed`
- No color change

---

## Components

### Button — Primary

```
bg: #f4f4f5 (zinc-100)   text: #09090b   font: sans 0.875rem 500
px: 1.25rem  py: 0.625rem  radius: 6px
hover-bg: #ffffff
```

### Button — Secondary / Ghost

```
bg: transparent   border: 1px solid #3f3f46   text: #d4d4d8   font: sans 0.875rem 500
px: 1.25rem  py: 0.625rem  radius: 6px
hover-border: #52525b   hover-text: #f4f4f5
```

### Button — Danger

```
bg: transparent   border: 1px solid #991b1b   text: #f87171
hover-bg: #1a0000   hover-border: #b91c1c
```

### Button — Accent (use rarely, e.g. submit pack)

```
bg: #22c55e   text: #09090b   font: sans 0.875rem 600
hover-bg: #4ade80
radius: 6px
```

### Input / Textarea

```
bg: #09090b or #111113   border: 1px solid #3f3f46   text: #f4f4f5
placeholder: #52525b   font: sans 0.875rem
px: 0.75rem  py: 0.625rem  radius: 6px
focus: border → #71717a  (no glow, no shadow)
transition: border-color 150ms ease
```

Mono inputs (slug, hash, version): `font-family: mono`

### Card / Panel

```
bg: rgba(#111113, 0.3) default  →  #111113 on hover
border: 1px solid #27272a  →  #3f3f46 on hover
radius: 8px
padding: 1.25rem (20px)
transition: background-color 150ms, border-color 150ms
```

### Status Badge

```
font: mono  size: 10px  weight: 600  tracking: 0.08em  uppercase
px: 0.5rem  py: 0.125rem  radius: 4px  border: 1px solid
```

Colors: see Status colors table above.

### Role Badge

Same shape as Status Badge. Colors:

| Role | Text | Background | Border |
|------|------|------------|--------|
| ADMIN | `#c084fc` (purple-400) | `#1a0030` (purple-950) | `#7e22ce` (purple-800) |
| REGISTRY_STEWARD | `#38bdf8` (sky-400) | `#001a2e` (sky-950) | `#075985` (sky-800) |
| MAINTAINER | `#4ade80` (green-400) | `#052e16` (green-950) | `#166534` (green-800) |
| REVIEWER | `#fbbf24` (amber-400) | `#1c0a00` (amber-950) | `#92400e` (amber-800) |
| PACK_CREATOR | `#fb923c` (orange-400) | `#1a0a00` (orange-950) | `#9a3412` (orange-800) |
| CONTRIBUTOR | `#94a3b8` (slate-400) | `#0f172a` (slate-900) | `#334155` (slate-700) |
| USER | `#71717a` (zinc-500) | `#18181b` (zinc-800) | `#3f3f46` (zinc-700) |

### Table

```
font: 0.875rem  border-collapse: collapse  width: 100%

thead:
  border-bottom: 1px solid #3f3f46
  th: mono 0.75rem uppercase letter-spacing: 0.05em  color: #71717a
      padding: 0.5rem 1rem  text-align: left

tbody:
  td: color #d4d4d8  padding: 0.6rem 1rem  border-bottom: 1px solid #27272a
  td:first-child: mono color #f4f4f5  (key/identifier column)
  last row: no border-bottom
  hover row: bg #18181b
```

### Divider / HR

```
border-color: #27272a  margin: 2rem 0
```

---

## Terminal Panel

The signature component. Used in hero and wherever live system output is displayed.

### Shell chrome

```
bg: #111113   border-bottom: 1px solid #27272a
height: 44px  px: 1rem  flex items-center gap: 0.5rem

Traffic lights: 3 × (width/height: 12px, radius: 50%, bg: #3f3f46)
Title: mono 0.75rem  color: #71717a  ml: 0.75rem  user-select: none
Counter (optional): mono 0.75rem  color: #3f3f46  ml: auto
```

### Terminal body

```
bg: #09090b   px: 1.25rem  py: 1.25rem
font: mono 0.875rem  line-height: 1.75
min-height: 200px
```

### Line color types

| Type | Color | Hex | Usage |
|------|-------|-----|-------|
| `cmd` | green-400 | `#4ade80` | User commands (`$ ...`) |
| `output` | zinc-400 | `#a1a1aa` | Standard output |
| `system` | zinc-500 | `#71717a` | Internal system messages (`[classifier]`, `[broker]`) |
| `success` | green-400 | `#4ade80` | Completion lines (`✓ ...`) |
| `error` | red-400 | `#f87171` | Error output |

### Blinking cursor

```css
.cursor-blink {
  display: inline-block;
  width: 8px;
  height: 1em;
  background-color: #22c55e;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 1.1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
```

---

## Animations & Motion

Keep motion minimal. Every animation must have a functional reason.

### Live status dot

Green pulsing dot for "service online" indicators:

```css
.status-live {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #22c55e;
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.5; transform: scale(1.25); }
}
```

### Fade transition (between terminal sequences, modals, panels)

```
opacity: 0 → 1   duration: 380ms   easing: ease
```

### All other transitions

```
duration: 150ms   easing: ease
properties: background-color, border-color, color, opacity
NO: transform animations on layout elements, no spring physics, no bounces
```

---

## Scrollbar

```css
::-webkit-scrollbar        { width: 6px; height: 6px; }
::-webkit-scrollbar-track  { background: #09090b; }
::-webkit-scrollbar-thumb  { background: #27272a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3f3f46; }
```

---

## Selection

```css
::selection {
  background-color: #22c55e30;
  color: #f4f4f5;
}
```

---

## Layout Conventions

- Max content width: `1280px` (7xl), centered, `px: 1rem / 1.5rem / 2rem` (sm/md/lg)
- Consistent section vertical padding: `py: 4rem` (64px) on desktop
- Grid gap for cards: `1.25rem` (20px)
- Sidebar width (docs, settings): `220px`
- Sticky header height: `56px` (h-14)
- Header: `bg: rgba(#09090b, 0.9)`, `backdrop-filter: blur(12px)`, `border-bottom: 1px solid #27272a`

---

## CSS Variables (define at `:root`)

If not using Tailwind, define these at the top of your stylesheet:

```css
:root {
  --bg:               #09090b;
  --surface:          #111113;
  --surface-hover:    #18181b;
  --border:           #27272a;
  --border-subtle:    #3f3f46;
  --border-active:    #52525b;
  --text:             #f4f4f5;
  --text-body:        #d4d4d8;
  --text-muted:       #a1a1aa;
  --text-faint:       #71717a;
  --text-ghost:       #52525b;
  --green:            #22c55e;
  --green-dim:        #16a34a;
  --blue:             #38bdf8;
  --amber:            #f59e0b;
  --red:              #ef4444;
  --orange:           #f97316;
  --font-sans:        'Geist', 'Inter', system-ui, sans-serif;
  --font-mono:        'Geist Mono', 'JetBrains Mono', ui-monospace, monospace;
  --radius-sm:        4px;
  --radius-md:        6px;
  --radius-lg:        8px;
  --transition-fast:  150ms ease;
  --transition-fade:  380ms ease;
}
```
