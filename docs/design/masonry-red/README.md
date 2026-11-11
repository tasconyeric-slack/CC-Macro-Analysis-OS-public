# Masonry Red

A photography-first discovery system: a masonry grid of image cards, quiet warm-cream chrome, and one saturated red reserved for the main action.

> **Source.** Built from `DESIGN-pinterest.md`, an analysis of a photo-discovery site's logged-out marketing and search pages. Every value is copied from it. Two substitutions: the source's proprietary face becomes **Inter**, and no logo or wordmark is included, so the system shows plain type where a brand mark would go.

## Principles

1. **Get out of the photograph's way.** The imagery is the product. Chrome is warm gray and white and never competes with it.
2. **One red, used sparingly.** `primary` (`#e60023`) carries the primary CTA, the active-tab indicator and the wordmark, and nothing else. At most one red CTA per fold, nav included.
3. **The image is the card.** Pin cards have no padding. Metadata floats over the image as a pill or avatar, never below it.
4. **Three shapes.** `radius-md` (16px) for nearly everything, `radius-lg` (32px) for big cards and modals, `radius-full` for pills and circles. Nothing in between, and no square controls.
5. **Flat by default.** No card shadows. Depth comes from photography. The only shadow is `shadow-modal`, over the `scrim`.
6. **Weight, not color, for hierarchy.** Body text stays `body` everywhere. Hierarchy comes from 400 → 600 → 700 and size.

## Content fundamentals

The voice is friendly, short and verb-led. It invites; it doesn't sell.

| Do | Don't |
|---|---|
| **Sign up** · **Get started** · **Continue** | Register now! · Submit |
| "Find ideas for dinner, decor and more" | "The #1 platform for visual inspiration" |
| Overlay pills name a search term: *Cherry red*, *Preppy look*, *Earthy space inspo* | Pills that describe the image ("Photo of lipstick") |
| Secondary actions are plain: *I already have an account*, *Cancel* | Guilt copy: "No thanks, I don't like ideas" |

Sentence case everywhere, including buttons and headings. No exclamation marks in chrome.

## Visual foundations

### Color

The chrome palette is warm neutrals: `canvas` (white), `surface-soft` (hero wash), `surface-card` (#f6f6f3, pin and tile fills), `secondary-bg` (#e5e5e0, secondary buttons). Text runs `ink` → `body` → `mute`, with `ash` for placeholders and disabled labels only, since it fails 4.5:1.

- `primary` on `canvas` or with `on-primary` text: CTAs only.
- `ink-soft` is for inline body links only, never chrome.
- `focus-outer` + `focus-inner` form the double focus ring on every focusable element.
- Editorial accents (`accent-purple`, `accent-purple-deep`, `accent-pressed-blue`) belong inside content badges, never in chrome.
- Semantic: `error` for validation, `success-deep` on `success-pale` for success pills.

### Typography

One family, `--font-sans` (Inter standing in for the source's geometric sans), weights 400/500/600/700.

- The jump is steep: `display-xl` (70px) goes straight to `body-md` (16px) on the hero, with nothing between.
- `display-xl`, `display-lg` and `heading-xl` carry **negative tracking** (-1.2 / -0.8 / -1.2px). It is part of the voice; keep it on any substitute face.
- Body sits at 1.4 line-height.
- Buttons use `button-md` (14/700); overlay pills use `button-sm` (12/700).

### Layout

- **Section rhythm:** `space-section` (64px) between major blocks; 48px at tablet, 32px at mobile.
- **Masonry grid:** columns, not rows. Each card keeps its natural aspect ratio (1:1, 2:3, 3:4, 4:5; landscape is rare). Gutters are `space-sm` (8px) both ways, 6px on mobile.
- **Columns by width:** 5–6 at 1920px+, 4 at desktop, 3 below 1024, 2 below 768, 1 below 480.
- **Content width:** `size-content` (1280px) with `space-xl` (24px) gutters.
- **Two modes share one chrome:** the *magazine* (hero, alternating left/right feature cards, CTA strip, footer: generous space) and the *search engine* (nav, filter chips, tight masonry: dense).

### Elevation

| Level | Treatment | Use |
|---|---|---|
| 0 Flat | none | Pin cards, feature cards, footer: the default |
| 1 Hairline | 1px `hairline` | Footer top rule, inner-page nav bottom rule, rows |
| 2 Modal | `scrim` + `shadow-modal` | Login/signup and image preview modals |

### Shape

| Token | Value | Use |
|---|---|---|
| `radius-none` | 0 | Nav, footer, section bands |
| `radius-md` | 16px | Buttons, inputs, pin cards, tiles, feature cards |
| `radius-lg` | 32px | Large feature pins, modal cards |
| `radius-full` | pill | Search bar, chips, overlay pills, icon buttons, avatars |

## Iconography

No icon set ships with this system. Icons are simple filled glyphs in `ink` at 20–24px, centered in a 40px `icon-button` (circular, `surface-card` fill). Common glyphs: magnifier (search bar, left edge), close (modal), chevrons (carousel paddles), share, more (•••). Bring your own set and keep strokes solid, not outline-thin.

## Imagery

- Real photography only: food, fashion, interiors, close-ups. Composition carries the depth.
- Preserve each image's natural ratio at every breakpoint; the column count changes, never the aspect.
- Category thumbnails are 1:1. Feature imagery is 4:5 portrait, re-cropped to square on mobile.
- The previews here use flat warm blocks as stand-ins for photos.

## Components

| Component | Role |
|---|---|
| Button | Primary (red), secondary (gray-cream), tertiary (ghost), disabled |
| IconButton | 40px circular icon control |
| SearchBar | Pill search field centered in the nav |
| TextInput | 44px field with the double-ring focus |
| FilterChip | Pill chip that inverts to `ink` when active |
| PinCard | Full-bleed image card with overlay pill and avatar |
| MasonryGrid | Column grid of pin cards, 8px gutters |
| CategoryTile | Square thumbnail + label tile |
| FeatureCard | Image + headline + CTA, alternating sides |
| ModalCard | Signup/login card over a scrim |
| CtaStrip | Dark full-width CTA band |
| PrimaryNav | 64px sticky nav, red CTA always visible |
| Footer | 4-column link grid with hairline top rule |
| InlineLink | `ink-soft` anchor in body prose |

All components are plain HTML + CSS: link `tokens.css` and `components/bundle.css` and use the `mr-` classes shown in each preview.

## Do & don't

**Do**
- Keep `primary` scarce: CTAs, active tab, wordmark.
- Use `radius-md` on every control and standard card.
- Stage every image in a PinCard with zero padding.
- Tighten grids to 8px; space sections at 64px.
- Keep the negative tracking on display and `heading-xl`.

**Don't**
- Don't use square buttons or cards.
- Don't add drop shadows to cards.
- Don't pad a pin card or put its text below the image.
- Don't substitute another red for `#e60023`.
- Don't use `ink-soft` outside inline links.
- Don't add a radius between 16 and 32px.
- Don't document or design hover lifts. The source covers default and pressed states only.

## Responsive

| Breakpoint | Change |
|---|---|
| 1920+ | 5–6 grid columns; content holds at 1280px |
| 1024 | 3 columns |
| 768 | 2 columns; nav becomes a hamburger; search becomes an icon |
| 480 | 1 column; hero 70 → 44px; modal becomes a bottom sheet (top corners `radius-lg`) |
| 320 | Hero ~36px; sections 32px apart |

Touch targets: buttons are 40px tall, inputs 44, search 48. Icon buttons pad their hit area to 48×48.

## Known gaps

From the source: no hover states, no pin-detail view, no logged-in chrome, no native app screens, no inline validation states beyond focus. Mobile behavior is inferred.


---

## Consuming this system (generated — do not edit)

Every path named below is under `project/` in this design system: read `project/api/tokens.md`, not `api/tokens.md`.

14 components are documented without a runnable `components/bundle.js`: read each component’s card, and its README where it has one (`components/<Comp>/README.md`), and build to those guidelines. Tokens: the values are on `api/tokens.md`; a Slides deck or Design canvas also takes `tokens.json` by file path. On a Design canvas, also copy `tokens.css` to `project/ds/<folder>/tokens.css` in the call that installs this system, and link it in each artboard that uses this system, right after the `support.js` line and before the system’s other stylesheets: `<link rel="stylesheet" href="ds/<folder>/tokens.css">` (with one `../` in front for each folder the artboard is in).

**Read, per thing:** a component’s props, parts and examples: `api/components/<Comp>.md`; token values: `api/tokens.md`. After this README, fetch the cards and fonts you need in ONE message as parallel calls — none depends on another.

**Two rules.** Before you use a thing — a component, a token group, an icon, an asset — read its card from the index below; a value you did not read from a card is a guess. `tokens.json`, `manifest.json` and `design-system.json` are sources for tools: hand them over. `components/<Comp>/README.md` is the long-form second read a card links to; `SKILL.md` and `artifact-type/` beside them are authoring guidance, not needed to consume the system.

## Index (generated — do not edit)

**Tokens**

- `api/tokens.md` — Every token: surface, text, fill, border, palette, type, spacing, radius, shadow, size. (11.5k)

**Components** (`api/components/<Comp>.md`, 14)

- **Actions**: `Button` — The 40px, 16px-radius action control: red primary, gray-cream secondary, ghost tertiary · `IconButton` — A 40px circular icon control for carousel paddles, modal close and small floating actions
- **Content**: `CategoryTile` — A cream tile pairing a square thumbnail with a short category label, shown 3 or 4 across · `CtaStrip` — A rare full-width dark band with a headline on the left and one red CTA on the right · `FeatureCard` — A two-column marketing row pairing a 4:5 photo with a headline, body copy and one red CTA · `InlineLink` — An anchor inside body prose, set apart by weight and a near-black warm tint rather than by color · `MasonryGrid` — A column-based grid of PinCards that keeps every image's natural ratio, with 8px gutters · `PinCard` — The image is the card: a full-bleed photo at its natural ratio inside 16px corners, with zero padding
- **Inputs**: `FilterChip` — A pill toggle for the filter strip above search results; it inverts fully when active · `SearchBar` — The 48px pill search field anchored in the center of the primary nav · `TextInput` — A 44px form field with a 16px radius and the signature double-ring focus
- **Navigation**: `Footer` — A quiet 4-column link grid under a hairline top rule · `PrimaryNav` — The 64px sticky top bar: brand left, pill search centered, account actions right, with the red Sign up always visible
- **Overlays**: `ModalCard` — The signup / login card that floats over a 50% scrim instead of navigating away
