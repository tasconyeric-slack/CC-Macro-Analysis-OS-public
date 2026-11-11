# SearchBar

The 48px pill search field anchored in the center of the primary nav.

- Class `mr-search` on a `<label>` that wraps a magnifier SVG and an `<input>`.
- Default: `surface-card` fill, `ink` text, `body-md`, padding 11px 15px, `radius-full`, height `size-search`.
- Focused (`:focus-within`): fill flips to `canvas` with a 1px `ash` border; size does not change.
- Placeholder in `mute`, e.g. "Search for ideas, recipes, style…".
- Width: about 480px at desktop, about 320px at tablet; on mobile it collapses to an IconButton that opens a full-width overlay.
