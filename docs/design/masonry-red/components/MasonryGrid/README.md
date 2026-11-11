# MasonryGrid

A column-based grid of PinCards that keeps every image's natural ratio, with 8px gutters.

- Class `mr-masonry`; children are `mr-pin` cards. CSS columns fill top-to-bottom per column; for left-to-right reading order, place cards with JS into the shortest column.
- Gutters `space-sm` (8px) on both axes, `space-xs` (6px) on mobile, so images almost touch.
- Columns: 5–6 at 1920px+, 4 at desktop, 3 at ≤1024, 2 at ≤768, 1 at ≤480. The column count changes; the image ratio never does.
- Content width caps at `size-content` with `space-xl` page gutters.
- Load more rows as the user scrolls; lazy-load images.
