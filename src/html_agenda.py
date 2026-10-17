"""Configurable reader for venue agendas published as plain HTML.

A venue whose site prints its programme as repeated blocks (one per concert)
but offers no structured data is described in config/venues.json with a
``feed`` of kind ``html``: the listing URL, the selector of one block, and a
selector per field. Nothing is inferred from prose: a block without a
recognisable date is skipped, past dates are skipped, and the text goes in
exactly as the venue prints it. Example (Sidecar):

    "feed": {"kind": "html", "url": "https://sidecar.es/programacio/", "item": "div.info-box",
             "fields": {"title": "a.title", "url": "a.title@href", "date": "a.date", "category": "a.category", "price": ".tickets span", "tickets": ".tickets a@href"},
             "skip": {"category": ["DJ session"]}}

Selectors are a small CSS subset: ``tag``, ``.class``, ``tag.class.other``,
descendant chains separated by spaces, and ``@attr`` to read an attribute
instead of the text. A field whose selector matches several elements joins
their texts with " + " (Sala Vol lists each act of a night in its own div).
A missing ``date`` or ``price`` selector falls back to a pattern search over
the block's text (dd/mm/yyyy or dd.mm.yyyy, optional hh:mm; "12/15€").
"""
from __future__ import annotations

import datetime as dt
import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b(?:\D{0,6}(\d{1,2})[:.h](\d{2}))?")
PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?(?:\s*/\s*\d{1,3}(?:[.,]\d{1,2})?)?\s*\+?\s*€|€\s*\d{1,3}(?:[.,]\d{1,2})?|\b(?:gratis|gratuït|gratuit|entrada lliure|free)\b)", re.I)
VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def text(self):
        out = []
        for child in self.children:
            out.append(child if isinstance(child, str) else " " + child.text() + " ")  # element boundaries separate words ("<div>Divendres</div><div>02/10…")
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document"); self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1]); self.stack[-1].children.append(node)
        if tag not in VOID: self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs, self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag: del self.stack[i:]; return

    def handle_data(self, data):
        if self.stack[-1].tag in ("script", "style"): return
        if data: self.stack[-1].children.append(data)


def parse(page):
    builder = _Builder(); builder.feed(page); return builder.root


def _matches(node, simple):
    m = re.fullmatch(r"([a-zA-Z0-9]*)((?:\.[\w-]+)*)", simple)
    if not m: raise ValueError("Selector no admitido: %s" % simple)
    tag, classes = m.group(1).lower(), {c for c in m.group(2).split(".") if c}
    if tag and node.tag != tag: return False
    return classes <= node.classes()


def select(root, selector):
    """Nodes matching a descendant chain of simple selectors ("div.info-box a.title")."""
    parts = selector.split()
    current = [root]
    for simple in parts:
        found = []
        for base in current:
            for node in base.walk():
                if _matches(node, simple) and node not in found: found.append(node)
        current = found
    return current


def field(item, selector, base_url=""):
    """Text (or @attribute) of a selector inside one block; several matches join with ' + '."""
    if not selector: return ""
    path, _, attr = selector.partition("@")
    nodes = [item] if path.strip() in ("", ".") else select(item, path.strip())
    if attr:
        values = [html.unescape(n.attrs.get(attr, "")) for n in nodes if n.attrs.get(attr)]
        return urljoin(base_url, values[0]) if values else ""
    texts = [n.text() for n in nodes if n.text()]
    return " + ".join(dict.fromkeys(texts))


def parse_date(text):
    """(YYYY-MM-DD, HH:MM or '') from the venue's own wording, or None."""
    m = DATE_RE.search(text or "")
    if not m: return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100: year += 2000
    try: date = dt.date(year, month, day)
    except ValueError: return None
    time = f"{int(m.group(4)):02d}:{m.group(5)}" if m.group(4) else ""
    return date.isoformat(), time


def parse_price(text):
    m = PRICE_RE.search(text or "")
    return m.group(0).strip() if m else ""


def events_from_html(page, feed, base_url, today=None):
    """Event nodes (schema.org shaped) for every block of the listing that carries a future date."""
    today = today or dt.date.today()
    root = parse(page); fields = feed.get("fields", {}); skip = feed.get("skip", {})
    out = []
    for item in select(root, feed["item"]):
        title = field(item, fields.get("title", ""), base_url)
        if not title: continue
        when = parse_date(field(item, fields["date"], base_url) if fields.get("date") else item.text())
        if not when or when[0] < today.isoformat(): continue
        values = {name: field(item, sel, base_url) for name, sel in fields.items()}
        if any(values.get(name, "").casefold() in {v.casefold() for v in wanted} for name, wanted in skip.items() if values.get(name)): continue
        price = values.get("price") or parse_price(item.text())
        node = {"@type": "Event", "name": title, "startDate": f"{when[0]}T{when[1]}:00" if when[1] else when[0], "endDate": when[0],
                "url": values.get("url") or base_url, "location": {"@type": "Place", "name": feed.get("venue_name", ""), "address": {"@type": "PostalAddress", "addressLocality": "Barcelona"}}}
        if price or values.get("tickets"):
            node["offers"] = {"@type": "Offer"}
            if price: node["offers"]["price"] = price
            if values.get("tickets"): node["offers"]["url"] = values["tickets"]  # the venue's own ticket link (DICE, Entradium…): shown as "Entradas"
        if values.get("category"): node["genre"] = values["category"]
        if values.get("style"): node["genre"] = (node.get("genre", "") + " · " + values["style"]).strip(" ·")
        out.append(node)
    return out
