"""The built site: the same pages in both languages, working language switch, links, fragments and metadata."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml

import localization as L
from conftest import LOCALES, PAGES, ROOT
from htmlutil import parse

# Owner-approved public origin: Vercel project `ccmacrors`, served through its custom domain.
SITE_URL = "https://ccmacro.byliyz.com"


def pages(built):
    return {(loc, name): parse(built / loc / name) for loc in LOCALES for name in PAGES}


def test_each_language_has_the_same_portal_pages_plus_selector_and_legacy_redirects(built):
    for loc in LOCALES:
        # news-edition-*/news-archive-* pages are generated from the dated news files
        assert sorted(p.name for p in (built / loc).glob("*.html") if not p.name.startswith(("news-", "macro-weekly-", "macro-monthly-"))) == PAGES
    root = sorted(p.name for p in built.glob("*.html"))
    assert root == PAGES                      # index.html = selector; the others = V1.0 URLs that now redirect
    assert (built / "static/style.css").is_file()


def test_html_lang_title_and_description_are_localized(built):
    for (loc, name), p in pages(built).items():
        assert p.lang == ("zh-Hans" if loc == "zh" else "en"), (loc, name)
        assert p.title.strip(), (loc, name)
        desc = next(m["content"] for m in p.meta if m.get("name") == "description")
        assert desc.strip()
        assert bool(L.CJK.search(p.title)) == (loc == "zh"), f"{loc}/{name}: title language {p.title!r}"
        assert bool(L.CJK.search(desc)) == (loc == "zh"), f"{loc}/{name}: description language"
    for name in PAGES:                          # a page's title differs between languages
        assert pages(built)[("en", name)].title != pages(built)[("zh", name)].title


def test_canonical_hreflang_and_open_graph(built):
    for (loc, name), p in pages(built).items():
        stem = name[:-5]
        url = lambda l: f"{SITE_URL}/{l}/" if stem == "index" else f"{SITE_URL}/{l}/{name}"
        assert p.canonical == url(loc)
        assert dict(p.alternates) == {"en": url("en"), "zh-Hans": url("zh"), "x-default": f"{SITE_URL}/"}
        og = {m["property"]: m["content"] for m in p.meta if "property" in m}
        assert og["og:url"] == url(loc) and og["og:type"] == "website"
        assert og["og:title"] == p.title.strip()
        assert og["og:locale"] == L.OG_LOCALE[loc] and og["og:locale:alternate"] == L.OG_LOCALE["zh" if loc == "en" else "en"]
        assert og["og:image"] == f"{SITE_URL}/static/og-{loc}.png"
        assert og["og:image:width"] == "1200" and og["og:image:height"] == "630" and og["og:image:alt"]
        assert (built / "static" / f"og-{loc}.png").stat().st_size > 5_000
        assert any(m.get("name") == "twitter:card" for m in p.meta)
        assert p.icons, f"{loc}/{name}: no favicon links"
    assert (built / "favicon.ico").is_file()


def test_canonical_origin_is_the_public_custom_domain():
    """All builds must publish metadata for the custom-domain production site."""
    assert yaml.safe_load((ROOT / "site/site.yaml").read_text(encoding="utf-8"))["url"] == SITE_URL


def test_absolute_urls_are_the_same_for_every_host(built):
    """Vercel production and any other host build one artifact. The only host name in it is configured in
    site/site.yaml; a deploy-preview or branch URL, Vercel, or localhost must not leak in from the environment."""
    for f in built.rglob("*.html"):
        text = f.read_text(encoding="utf-8").replace(SITE_URL, "")
        assert "netlify" not in text.lower() and "vercel" not in text.lower() and "localhost" not in text, f


def test_root_selector_and_legacy_redirects_also_point_at_the_canonical_origin(built):
    """The selector page and the V1.0 flat URLs carry their own metadata (root.html / legacy.html)."""
    root = parse(built / "index.html")
    assert root.canonical == f"{SITE_URL}/"
    assert dict(root.alternates) == {"en": f"{SITE_URL}/en/", "zh-Hans": f"{SITE_URL}/zh/", "x-default": f"{SITE_URL}/"}
    for name in PAGES:
        p = parse(built / name)
        og = {m["property"]: m["content"] for m in p.meta if "property" in m}
        assert og["og:image"] == f"{SITE_URL}/static/og-en.png", name
        assert og["og:url"] == p.canonical, name
        want = f"{SITE_URL}/" if name == "index.html" else f"{SITE_URL}/en/{name}"
        assert p.canonical == want, name


def test_language_switch_points_to_the_equivalent_existing_page(built):
    for (loc, name), p in pages(built).items():
        other = "zh" if loc == "en" else "en"
        assert len(p.switch) == 1, f"{loc}/{name}: expected one switch link, got {p.switch}"
        href, base, lang = p.switch[0]
        assert lang == other and href == base == f"../{other}/{name}"
        target = (built / loc / href).resolve()
        assert target == (built / other / name).resolve() and target.is_file(), f"{loc}/{name} -> {href}"
        assert p.current_lang == ["zh-Hans" if loc == "zh" else "en"]   # the current language is shown, not linked
        assert 'data-base' in (built / loc / name).read_text(encoding="utf-8")


def test_switch_target_check_catches_a_missing_page(built, tmp_path):
    """The check above must fail if a page exists in one language only."""
    broken = tmp_path / "dist"
    shutil.copytree(built, broken)
    (broken / "zh" / "evidence.html").unlink()
    p = parse(broken / "en" / "evidence.html")
    href = p.switch[0][0]
    assert not (broken / "en" / href).resolve().is_file()


def test_element_ids_match_across_languages_so_fragments_survive_a_switch(built):
    pg = pages(built)
    for name in PAGES:
        en, zh = pg[("en", name)], pg[("zh", name)]
        assert sorted(en.ids) == sorted(zh.ids), f"{name}: ids differ {set(en.ids) ^ set(zh.ids)}"
        assert len(set(en.ids)) == len(en.ids), f"{name}: duplicate ids {[i for i in set(en.ids) if en.ids.count(i) > 1]}"


def test_every_internal_link_and_fragment_resolves(built):
    ids = {}

    def page_ids(path):
        if path not in ids:
            ids[path] = set(parse(path).ids)
        return ids[path]
    checked = 0
    for f in sorted(built.rglob("*.html")):
        p = parse(f)
        for ref in p.hrefs + p.srcs:
            u = urlsplit(ref)
            if u.scheme in ("http", "https", "mailto") or ref.startswith("data:"):
                continue
            target = (f.parent / unquote(u.path)).resolve() if u.path else f.resolve()
            if target.is_dir():
                target = target / "index.html"
            assert target.is_file(), f"{f.relative_to(built)}: broken link {ref}"
            if u.fragment and target.suffix == ".html":
                assert unquote(u.fragment) in page_ids(target), f"{f.relative_to(built)}: {ref} has no #{u.fragment}"
            checked += 1
    assert checked > 300   # sanity floor: the walk really covered the site


def test_no_version_of_the_site_links_to_the_wrong_language(built):
    """Internal page links stay inside the language they are on (only the switch crosses over)."""
    for (loc, name), p in pages(built).items():
        other = "zh" if loc == "en" else "en"
        crossing = [h for h in p.hrefs if f"../{other}/" in h and h != f"../{other}/{name}"]
        assert not crossing, f"{loc}/{name}: {crossing}"


# ---------------------------------------------------------------- the root selector and legacy URLs
NODE = shutil.which("node")


def selector_script(path):
    return next(s for s in parse(path).scripts if "localStorage" in s and "location.replace" in s)


def run_selector(script, stored, languages, url_suffix=""):
    # wrapped in a function so these locals shadow Node's own `navigator`
    harness = f"""
      (function () {{
        var stored = {json.dumps(stored)}, navLangs = {json.dumps(languages)}, out = null;
        var localStorage = {{ getItem: function () {{ if (stored === 'THROW') throw new Error('blocked'); return stored; }} }};
        var navigator = {{ languages: navLangs, language: navLangs[0] || '' }};
        var location = {{ search: '', hash: {json.dumps(url_suffix)}, replace: function (u) {{ out = u; }} }};
        {script}
        console.log(out);
      }})();
    """
    return subprocess.run([NODE, "-e", harness], capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("stored,languages,expected", [
    ("zh", ["en-US"], "zh/"),                  # a stored choice wins over the browser
    ("en", ["zh-CN"], "en/"),
    (None, ["zh-CN", "en"], "zh/"),            # else the browser language
    (None, ["zh-Hant-TW"], "zh/"),
    (None, ["fr-FR", "en-GB"], "en/"),         # first supported language in the browser's order
    (None, ["fr-FR", "de"], "en/"),            # else English
    (None, [], "en/"),
    ("garbage", ["zh"], "zh/"),                # an unknown stored value is ignored
    ("THROW", ["zh"], "zh/"),                  # blocked storage (private window) must not break it
])
def test_root_selector_chooses_stored_then_browser_then_english(built, stored, languages, expected):
    assert run_selector(selector_script(built / "index.html"), stored, languages) == expected


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_legacy_flat_urls_forward_to_the_locale_and_keep_the_fragment(built):
    script = selector_script(built / "evidence.html")
    assert run_selector(script, "zh", ["en"], "#H2") == "zh/evidence.html#H2"
    assert run_selector(script, None, ["en-US"], "#rules") == "en/evidence.html#rules"
    assert 'name="robots" content="noindex"' in (built / "evidence.html").read_text(encoding="utf-8")
    # the selector page itself is indexable and links both languages without JavaScript
    root = parse(built / "index.html")
    assert {h for h in root.hrefs if h in ("en/", "zh/")} == {"en/", "zh/"}


def test_switch_script_carries_the_fragment_and_remembers_only_an_explicit_choice():
    js = (ROOT / "site/static/site.js").read_text(encoding="utf-8")
    assert 'a.getAttribute("data-base") + location.hash' in js         # fragment kept
    assert "hashchange" in js                                           # ... and kept current
    assert "localStorage.setItem" in js and js.count("localStorage.setItem") == 1
    assert "toLowerCase" in js                                          # #h2 finds #H2
    root = (ROOT / "site/templates/root.html").read_text(encoding="utf-8")
    assert "location.search + location.hash" in root
