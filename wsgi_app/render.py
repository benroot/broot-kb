import os
import re

import mistune
import yaml

import config

from . import links

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?", re.DOTALL)

WIKILINK_PATTERN = r"\[\[(?P<wikilink_target>[^\]|]+)(?:\|(?P<wikilink_display>[^\]]+))?\]\]"
EMBED_PATTERN = r"!\[\[(?P<embed_target>[^\]]+)\]\]"

# Matches a `> [!type] optional title` line plus any further contiguous `>`
# lines. Obsidian callouts are ordinary blockquotes, so title and body are
# often on adjacent lines with no blank line between them - by the time
# mistune's default block_quote rule renders that to HTML, title and body
# text have already been merged into a single <p>, making them impossible to
# tell apart. Handling this at the block-parsing stage (before that merge
# happens) instead avoids that. This doesn't handle a callout containing a
# blank-line-separated lazy continuation - an edge case not worth the extra
# complexity for a single-user tool.
CALLOUT_BLOCK_PATTERN = (
    r"^ {0,3}>[ \t]*\[!(?P<callout_type>[\w-]+)\][ \t]*(?P<callout_title>[^\n]*)\n"
    r"(?P<callout_rest>(?:^ {0,3}>.*(?:\n|$))*)"
)
CALLOUT_LINE_PREFIX_RE = re.compile(r"^ {0,3}>[ ]?", re.MULTILINE)


def split_frontmatter(raw_text):
    """Split leading YAML frontmatter off a raw note. Returns (dict, body)."""
    m = FRONTMATTER_RE.match(raw_text)
    if not m:
        return {}, raw_text
    body = raw_text[m.end():]
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        data = {}
    return data, body


def _parse_embed(inline, m, state):
    target = m.group("embed_target").strip()
    state.append_token({"type": "wiki_embed", "attrs": {"target": target}})
    return m.end()


def _render_wiki_embed(renderer, target):
    result = links.resolve(renderer.lookup, target)
    if result["kind"] == "media":
        ext = os.path.splitext(target)[1].lower()
        if ext in config.IMAGE_EXTENSIONS:
            return '<img class="embed-image" src="{}" alt="{}">'.format(
                result["url"], mistune.escape(target)
            )
        return '<a class="embed-file" href="{}">{}</a>'.format(
            result["url"], mistune.escape(target)
        )
    return '<span class="embed-broken" title="Missing media">{}</span>'.format(
        mistune.escape(target)
    )


def _parse_wikilink(inline, m, state):
    target = m.group("wikilink_target").strip()
    display = (m.group("wikilink_display") or target).strip()
    state.append_token({"type": "wikilink", "attrs": {"target": target, "display": display}})
    return m.end()


def _render_wikilink(renderer, target, display):
    result = links.resolve(renderer.lookup, target)
    if result["kind"] == "broken":
        return '<span class="wikilink-broken" title="Broken link">{}</span>'.format(
            mistune.escape(display)
        )
    return '<a class="wikilink" href="{}">{}</a>'.format(result["url"], mistune.escape(display))


def _parse_callout(block, m, state):
    callout_type = m.group("callout_type").lower()
    title = m.group("callout_title").strip()
    rest_raw = m.group("callout_rest")
    body_text = CALLOUT_LINE_PREFIX_RE.sub("", rest_raw)

    child = state.child_state(body_text)
    block.parse(child, block.block_quote_rules)

    state.append_token({
        "type": "callout",
        "attrs": {"callout_type": callout_type, "title": title},
        "children": child.tokens,
    })
    return m.end()


def _render_callout(renderer, text, callout_type, title):
    title_html = '<p class="callout-title">{}</p>'.format(mistune.escape(title)) if title else ""
    return '<div class="callout callout-{}">{}{}</div>\n'.format(callout_type, title_html, text)


def _wikilink_plugin(md):
    md.inline.register("wiki_embed", EMBED_PATTERN, _parse_embed, before="link")
    md.inline.register("wikilink", WIKILINK_PATTERN, _parse_wikilink, before="link")
    md.block.register("callout", CALLOUT_BLOCK_PATTERN, _parse_callout, before="block_quote")
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("wiki_embed", _render_wiki_embed)
        md.renderer.register("wikilink", _render_wikilink)
        md.renderer.register("callout", _render_callout)


class ObsidianRenderer(mistune.HTMLRenderer):
    """HTML renderer with a `lookup` slot the wikilink/embed rules read from."""

    def __init__(self, lookup):
        super().__init__()
        self.lookup = lookup


def render_note_body(raw_body, lookup):
    """Render a note's markdown body (frontmatter already stripped) to HTML,
    resolving wikilinks/embeds against `lookup` (see links.build_lookup)."""
    renderer = ObsidianRenderer(lookup)
    md = mistune.create_markdown(renderer=renderer, plugins=[_wikilink_plugin])
    return md(raw_body)
