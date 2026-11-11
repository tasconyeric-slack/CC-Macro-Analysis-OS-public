# PinCard

The image is the card: a full-bleed photo at its natural ratio inside 16px corners, with zero padding.

- Class `mr-pin` on a `<figure>`; the image gets `mr-pin__img` (an `<img>` with real width/height, or a ratio class `--1x1`, `--2x3`, `--3x4`, `--4x5`).
- Fill `surface-card` shows while the image loads. Radius `radius-md`; `mr-pin--lg` uses `radius-lg` for large feature pins.
- **Overlay pill** `mr-pill`: `canvas` fill, `ink` text in `button-sm`, padding 6px 12px, `radius-full`, inset `space-md` from the top-left (or `mr-pill--bottom`). It names a search term ("Cherry red"), not the image.
- **Attribution** `mr-pin__by`: a 32px `mr-avatar` plus the name in `body-sm-strong`, overlaid bottom-left.
- No padding, no shadow, no text below the image. Lazy-load images.
