# Production website acceptance — CC Macro Analysis OS

**Canonical public URL:** https://ccmacro.byliyz.com/
**Host:** Vercel project `ccmacrors` in `tasconyeric-slack`
**Source:** `tasconyeric-slack/CC-Macro-Analysis-OS`, production branch `main`
**Output:** `site/dist/` (static HTML, no server-side runtime)

This is the **only public-product acceptance surface** for subsequent releases and website reviews. `*.vercel.app` preview / alias URLs and any residual Netlify deployment are useful for debugging, but cannot substitute for the custom-domain production check. The one build-time public origin is `site/site.yaml:url`. All hosts build identical canonical/hreflang/Open Graph metadata; no host-dependent rewrite or second domain constant is required.

## After every change merged to main

1. Record the merged `main` commit SHA and the Vercel production deployment commit SHA. Both must match. Confirm Vercel reports **READY**, not just a successful preview. If the Vercel project API is unavailable, report the deployment check as **UNVERIFIED**, not PASS.
2. Open **https://ccmacro.byliyz.com/** in a clean browser session. Check that the static language selector works and that the English/Chinese links work with JavaScript disabled. It is acceptable for the root selector to redirect in the browser to a locale; it must not be a 404/403 or auth challenge.
3. Load the following paths on the **custom domain**, in both languages:
   - `/en/`, `/zh/`
   - `/en/memo.html`, `/zh/memo.html`
   - `/en/evidence.html`, `/zh/evidence.html`
   - `/en/updates.html`, `/zh/updates.html`
   - `/en/charts.html`, `/zh/charts.html`
   - `/en/method.html`, `/zh/method.html`
4. Check language switching on the corresponding page, including `#fragment` preservation; check navigation, styles, SVG charts and `/static/og-en.png`, `/static/og-zh.png`.
5. Inspect the returned HTML (not just the browser's address bar):
   - `/` canonical and `x-default` use `https://ccmacro.byliyz.com/`.
   - Localized `rel="canonical"`, `hreflang`, `og:url`, and `og:image` all use `https://ccmacro.byliyz.com`; no `netlify.app` or `vercel.app` origin leaks into public metadata.
   - The public content shows the latest committed research update, provenance and audit trail, including the immutable preregistration/amendment reference.
   - No private Wind/licensed data or credentials appear in the page/source or bundled assets.
6. Compare the visible evidence-as-of and latest-refresh timestamps with the committed research artifacts. A READY deployment with stale content is **not** accepted as a new release. Check both current view and release-update pages.
7. Run the existing gates on the PR/head or latest `main`: `pytest`, `python -m cnmacro check --public`, and `python site/build.py`. The repo's bilingual metadata, links, claim bindings, as-of and audit tests must pass. Retain the existing Vercel Python 3.14 build path, Netlify portability configuration, and append-only records.
8. If mainland-China reachability is part of the release claim, check the **custom domain** using a real mainland-China network, independently of Vercel READY and global uptime. Do not infer mainland reachability from DNS setup, an overseas probe, or a passing CI check.

## Pass / fail report

Record: `main SHA`, Vercel production deployment SHA + status, custom-domain reachability, bilingual routes, metadata, source/audit freshness, CI/eval, mainland access when tested, and any blockers. **Final product quality judgments use the custom-domain pages**; a preview/alias may diagnose an issue but cannot establish PASS.

## Remaining owner-controlled configuration

- Keep Vercel's `ccmacrors` project and custom domain assignment correct in the Vercel dashboard (including public Deployment Protection / Firewall settings). These are account settings, not repo files.
- Set the GitHub repository **About → Website** to `https://ccmacro.byliyz.com/` if it has not already been updated; that field is not controlled by `site/site.yaml`.
- `docs/PRODUCT_STRATEGY.md` §13.1 and its phase checklist contain a prior `vercel.app` canonical decision. The strategy document is explicitly **Owner-edit-only** under §20. Its domain wording should be reconciled by the Owner with this newly approved production contract; do not edit the frozen strategy or preregistered research files as part of a deployment-domain PR.
