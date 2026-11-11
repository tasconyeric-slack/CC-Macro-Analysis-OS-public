# Button

The 40px, 16px-radius action control: red primary, gray-cream secondary, ghost tertiary.

| Variant | Class | Fill / text | Use |
|---|---|---|---|
| Primary | `mr-btn mr-btn--primary` | `primary` / `on-primary` | Sign up, Continue, Get started |
| Secondary | `mr-btn mr-btn--secondary` | `secondary-bg` / `on-secondary` | I already have an account, Cancel |
| Tertiary | `mr-btn mr-btn--tertiary` | transparent / `ink` | Learn more, Read the docs |
| Disabled | `disabled` attribute | `surface-card` / `ash` | Unavailable action |

- Height `size-button` (40px), padding 6px 14px, label `button-md` (14/700), radius `radius-md`.
- Pressed: primary drops to `primary-pressed`, secondary to `secondary-pressed` (`:active`, or `.is-pressed` to show it statically).
- Focus: the double ring, `focus-inner` 2px inside `focus-outer`.
- **One red button per fold**, counting the nav's Sign up. Pair red with secondary, never with a second red.
- Hover is intentionally not specified.
- Add `mr-btn--block` for a full-width button in modals.

You provide the `<button>` (or `<a>`) element and its label.
