# Korda

A black and white brand built from one shape: the bar in the logo. It is a string pulled tight (*corda*), a text cursor, and a mark of emphasis. Everything else in the system is drawn from it.

This system is set up for **slide decks at 1920 × 1080**. Sizes in the tokens are slide sizes.

## Principles

- **Black, white, and four grays. Nothing else** — except the three status colors in the product UI (below). Color never carries meaning on its own; when a chart needs a "bad" value, use ink-500 against ink-900 and say it in words.
- **One idea per slide.** If a slide needs two headlines, it is two slides.
- **The bar is the only ornament.** No gradients, shadows, stock photos, or emoji. Icons label things; they never decorate.
- **Big type, few words.** Titles do the talking; body text supports them.

## Logo

| File | Use |
|---|---|
| `korda-wordmark-black.svg` | On white and light-gray slides |
| `korda-wordmark-white.svg` | On ink-900 and ink-800 |
| `korda-bar-black.svg`, `korda-bar-white.svg` | The mark alone: favicons, small corners, slide footers |
| `korda-icon-light.svg`, `korda-icon-dark.svg` | App icons and avatars (square tile, 8px corner) |

- **Clear space:** the width of two bars on every side.
- **Minimum size:** wordmark 24px tall on screen; the bar alone 16px tall.
- **On slides:** the wordmark is the cover's title, bottom-left at 160px tall; elsewhere it sits bottom-left at 32px tall.
- **Don't** stretch it, recolor it in grays, add effects, set "korda" in a typeface, or place it on photos.

## Color

Use the semantic tokens (`bg`, `surface`, `text`, `text-muted`, `mark`, `rule`) and pick the slide's theme; the primitives (`ink-900` … `paper`) are for when a slide must be one or the other regardless of theme.

- **Proportions across a deck:** about 70% white slides, 30% black. Black slides are for the cover, section dividers, statements, and the closing slide.
- **Contrast:** `text` and `text-muted` pass 4.5:1 on `bg` in both themes. `ink-500` on `ink-900` is only 3.9:1, which is why `text-muted` switches to `ink-100` on dark slides.
- **Product canvas (web app only):** the run graph in `apps/web` follows the flowchart language of [beautifului.dev](https://www.beautifului.dev/) (MIT, © 2026 Shane Levine): dotted canvas, cards with an 18px radius and soft shadow, and a colored type pill above each card. Type hues: input `#9A5CFF`, approval `#F09A2F`, agent `#3D7BFD`, tool `#14A39A`, output `#E0508F`. They label the kind of step only; the state is always in words, in a tinted status pill. Surface, text, line and status colors (green, orange, red) come from beautifului's published CSS, in light and dark, and replace the `status-*` values below inside the web app. Slides keep the rules above. Tokens live in `apps/web/src/app/globals.css`.
- **Status (product UI only):** `status-done` #3CBB71, `status-waiting` #E0A329, `status-failed` #C74238 mark the state of a step, test or approval. Always pair them with a text label (e.g. "falhou"); never use them on slides, in charts or as decoration. They are for dots, bars and borders, not for body text.

## Typography

**Inter**, loaded from Google Fonts (weights 400, 600, 700). Headlines are tight: 700 weight with negative tracking (−0.035em to −0.06em), matching the wordmark. Body stays at 400.

| Style | Size | Use |
|---|---|---|
| display | 160 | Cover, statements |
| title | 88 | Section dividers |
| heading | 56 | Content slide titles |
| subheading | 36 | Column heads, key points |
| body | 28 | Text and bullets (never smaller) |
| caption | 22 | Sources, page numbers |
| label | 18, uppercase | Eyebrows |
| numeral | 240 | Section numbers, one hero number |

Sentence case everywhere. Left-aligned; center only the cover statement if it is a single line.

## Layout

- Canvas 1920 × 1080. Margins: `space-7` (120px) left and right, `space-6` (96px) top and bottom.
- A 12-column grid inside the margins with 40px gutters (`space-4`).
- Footer on every content slide: the bar (16px) bottom-left, slide number bottom-right in `caption` / `text-muted`. A source line goes in the same row, 24px after the bar.

## Graphic elements

All four are made of the bar: `mark` color unless noted, width `bar-width-slide` (22px), corner `radius-bar`.

1. **Cursor.** A bar at the end of a headline, 8px after the last letter, as tall as the cap height plus descender (about 0.8 × font size). Use it on statement slides, once per slide. In the product, it can blink while the AI is writing.
2. **Taut line.** A 3px line held between two bars (6 × 24 px). Section dividers and agendas: finished and current sections in `mark`, sections still ahead in `rule`. Number and section name on the left, the line running to the right margin.
3. **Anchor.** A bar as tall as the text block, 40px to its left. Holds a quote, a key point, or a single number. One per slide.
4. **Hanging bar.** One oversized bar, 280 × 792 px, in `ink-800`, hanging from the top edge on the right margin: square top corners (it bleeds off the edge), 50px radius at the bottom. Covers and closing slides only; never put text over it.

## Iconography

**Heroicons**, outline style only (24px grid, 1.5 stroke), by Tailwind Labs, MIT license: free for commercial use, no credit needed on slides. A starter set of 24 sits in the Icons assets; the rest are at heroicons.com or in the `heroicons` npm package (`24/outline`).

- **Color:** `mark` only, so ink-900 on white slides and paper on black. Never gray, never two colors.
- **Size on slides:** 48px next to body text and in lists; 64px above a column head; 96px when one icon stands for a whole slide's point. Keep the 24px grid's proportions: never stretch.
- **Spacing:** 24px (`space-3`) from icon to its text; icons in a row sit on the column grid.
- **Style:** outline only. Don't mix in the solid or mini sets, don't put icons inside circles or tiles, and don't change the stroke width.
- **Use them to label, not to fill space.** One icon per item in a list or column, or none at all. A slide with a single message doesn't need one.

## Technology logos

When a slide or diagram names a real tool (PostgreSQL, AWS, Snowflake, Claude), show that tool's own logo, not a generic icon. 50 are in the Tech assets, from Simple Icons (CC0), recolored to ink-900.

- **Color:** single-color only, `mark` (ink-900 on white, paper on black). Never the vendor's brand colors: they break the black-and-white rule.
- **Size:** 40px in diagram blocks, 48px on slides next to the tool's name. Always with the name written beside or under it.
- **Placement:** on white (`paper`) or `ink-100` blocks with an ink-900 outline. Never stretch, crop or redraw a logo.
- **Missing a logo?** Get it from simpleicons.org and set its fill to #141414. Logos are trademarks of their owners: use them only to name the tool.

## Slide types

`TitleSlide` (cover, with the hanging bar), `SectionSlide` (divider with taut line), `ContentSlide` (text and a visual), `CardsSlide` (two or three full-height cards), `MetricSlide` (hero number and trend chart), `KeyPointSlide` (anchor), `StatementSlide` (one sentence with the cursor). `Icons` shows the icon set in use. Every component here is a layout to copy, not a coded component.

## Deck template

The full Korda deck template, with all twelve layouts ready to fill, lives at https://claude.ai/code/artifact/73448787-89ba-4df7-a3bf-51a10b93d72f. It has a cover, agenda, section divider, content, two cards, three cards, key point, metric, table, quote, statement and closing. Start new decks from a copy of it.

## Diagram template

Architecture and information diagrams live on the Korda architecture whiteboard: https://claude.ai/artifact/NxpqvBYWrQ7JPveLJqeyrX. It has a five-stage reference stack (Sources, Ingest, Store, Korda agents, Deliver) and a kit of all 50 logo tiles to copy.

- Read left to right; one section per stage, arrows only between stages.
- White blocks are third-party tools; `ink-100` blocks are what Korda builds. No other fills.
- Each block: the tool's logo at 40px, then its name in bold and its role in one or two words.

## Voice

Plain, direct, specific. Short sentences. Numbers over adjectives. Write placeholders as [brackets] rather than inventing figures.
