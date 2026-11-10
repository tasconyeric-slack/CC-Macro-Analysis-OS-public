# TextInput

A 44px form field with a 16px radius and the signature double-ring focus.

- Class `mr-input` inside an `mr-field` label with `mr-field__label` (14/600 `ink`).
- Default: `canvas` fill, 1px `ash` border, `ink` text in `body-md`, padding 11px 15px, height `size-input`, `radius-md`.
- Focused: 2px `ink` border plus a 4px `focus-outer` outline.
- Placeholder in `ash`; never put needed information in a placeholder (it fails 4.5:1).
- Helper text `mr-field__help` (12px `mute`); errors `mr-field__error` (12px `error`). The source documents no full validation state, so keep error styling to the message line.
- Used for email, password, birthdate and country in the signup modal.
