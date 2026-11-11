# ModalCard

The signup / login card that floats over a 50% scrim instead of navigating away.

- Scrim `mr-scrim`: `scrim` (50% black) over the whole page.
- Card `mr-modal`: `surface-elevated` fill, `radius-lg`, padding `space-xxl`, `shadow-modal`, about 420–480px wide. This is the only shadow in the system.
- Title `heading-lg` in `ink`; subtitle `body-md`; stacked TextInputs; one full-width primary "Continue"; a small "Already a member? Log in" line in `mute` with an InlineLink.
- Close: an IconButton top-right.
- Mobile: a full-width bottom sheet with `radius-lg` on the top corners only and the CTA anchored at the bottom.
- Trap focus inside, close on Escape, return focus to the trigger.
