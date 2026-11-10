# PrimaryNav

The 64px sticky top bar: brand left, pill search centered, account actions right, with the red Sign up always visible.

- Class `mr-nav`: `canvas` fill, `ink` links in `body-strong`, height `size-nav`, `radius-none`.
- Home: no bottom rule. Inner pages: `mr-nav--inner` adds a 1px `hairline` bottom rule.
- Left: the brand in `primary` (no logo ships with this system; use your own mark or plain type) plus "Explore". Active tab: a 3px `primary` underline.
- Center: a SearchBar, about 480px max.
- Right: secondary links, then the one `mr-btn--primary` "Sign up". This button is the fold's single red CTA.
- At ≤768px: hamburger left, brand center, search icon + Sign up right; the search bar collapses to an icon.
