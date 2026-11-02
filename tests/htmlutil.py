"""Small HTML helpers for tests (stdlib only)."""
from html.parser import HTMLParser
import re
from pathlib import Path

VOID = {"meta", "link", "br", "img", "hr", "input", "source", "col", "wbr"}
BLOCK = {"div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr", "td", "th", "dt", "dd", "dl", "section", "article",
         "summary", "details", "header", "footer", "main", "nav", "table", "thead", "tbody", "button", "br", "pre"}


class Page(HTMLParser):
    """ids, links, <a data-lang> switch links, <html lang>, <title>, meta tags, and the visible text
    with or without the contents of <details> (the 'technical lineage' that is collapsed by default)."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.ids, self.hrefs, self.srcs, self.meta, self.alternates = [], [], [], [], []
        self.lang, self.title, self.canonical = None, "", None
        self.switch = []          # (href, data-base, data-lang)
        self.current_lang = []    # span[aria-current] inside .lang
        self.icons = []
        self._stack, self._text_all, self._text_open, self._in_title = [], [], [], False
        self._script = None
        self.scripts = []
        self.feed(html)

    # -- parsing
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            self.meta.append(a)
        if tag == "link":
            if a.get("rel") == "canonical":
                self.canonical = a.get("href")
            if a.get("rel") == "alternate" and a.get("hreflang"):
                self.alternates.append((a["hreflang"], a.get("href")))
            if a.get("rel") in ("icon", "apple-touch-icon"):
                self.icons.append(a.get("href"))
            if a.get("href"):
                self.hrefs.append(a["href"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
            if "data-lang" in a:
                self.switch.append((a["href"], a.get("data-base"), a["data-lang"]))
        if tag == "script":
            self._script = []
            if a.get("src"):
                self.srcs.append(a["src"])
        if tag == "span" and "aria-current" in a:
            self.current_lang.append(a.get("lang"))
        if tag in BLOCK:
            self._gap()
        if tag not in VOID:
            self._stack.append(tag)

    def _gap(self):
        self._text_all.append(" ")
        self._text_open.append(" ")

    def handle_endtag(self, tag):
        if tag in BLOCK:
            self._gap()
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self._script is not None:
            self._script.append(data)
            return
        if self._in_title:
            self.title += data
        if "style" in self._stack or "svg" in self._stack:
            return
        self._text_all.append(data)
        if "details" not in self._stack:
            self._text_open.append(data)

    # -- views
    def text(self, include_details: bool = False) -> str:
        return re.sub(r"\s+", " ", "".join(self._text_all if include_details else self._text_open)).strip()


def parse(path: Path) -> Page:
    return Page(Path(path).read_text(encoding="utf-8"))
