# FeatureCard

A two-column marketing row pairing a 4:5 photo with a headline, body copy and one red CTA.

- Class `mr-feature`: `canvas` fill, padding `space-xxl`, `radius-md`. `mr-feature--soft` uses `surface-card` to break up alternate rows.
- Media `mr-feature__media`: 4:5 portrait, `radius-lg`, about 60% of the visual weight; may carry one overlay pill.
- Headline `heading-xl` (28/700, -1.2px) in `ink`; body `body-md` in `body`; then one `mr-btn--primary`.
- Rows alternate sides down the page: add `mr-feature--flip` to put the image on the right.
- Stack sections `space-section` apart. At ≤768px the card stacks with the image on top, re-cropped to square on mobile.
