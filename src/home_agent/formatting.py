"""Markdown to Telegram HTML conversion.

Converts LLM Markdown output to the limited HTML subset supported by Telegram.
Uses markdown-it-py token stream for reliable parsing (no regex).

Telegram-supported HTML tags:
  <b>, <i>, <u>, <s>, <code>, <pre>, <a href>, <tg-spoiler>, <blockquote>

Unsupported nodes (tables, images, HR) are rendered as plain text fallbacks.
"""

from __future__ import annotations

import html
import logging

from markdown_it import MarkdownIt
from markdown_it.token import Token

logger = logging.getLogger(__name__)

_md = MarkdownIt()


def md_to_telegram_html(text: str) -> str:
    """Convert Markdown text to Telegram-safe HTML.

    Parses the Markdown using markdown-it-py's token stream and emits only
    HTML tags supported by Telegram. Unknown nodes fall back to plain text.
    Raw & < > in plain text portions are HTML-escaped to prevent parse errors.

    Args:
        text: Markdown-formatted text from the LLM.

    Returns:
        HTML string safe to pass to Telegram with parse_mode=ParseMode.HTML.
        Falls back to html.escape(text) if conversion raises unexpectedly.
    """
    try:
        tokens = _md.parse(text)
        return _render_tokens(tokens)
    except Exception:
        logger.exception("md_to_telegram_html failed, falling back to plain text")
        return html.escape(str(text))


def _render_tokens(tokens: list[Token]) -> str:
    """Walk a markdown-it-py token list and emit Telegram HTML.

    Args:
        tokens: List of Token objects from markdown-it-py.

    Returns:
        Rendered HTML string.
    """
    out: list[str] = []
    for token in tokens:
        _render_token(token, out)
    return "".join(out)


def _render_token(token: Token, out: list[str]) -> None:
    """Render a single markdown-it-py token to Telegram-safe HTML.

    Args:
        token: A Token object from markdown-it-py.
        out: Output list to append rendered HTML fragments to.
    """
    t = token.type

    if t == "inline" and token.children:
        for child in token.children:
            _render_token(child, out)

    elif t == "paragraph_open":
        pass  # No <p> in Telegram; content follows inline

    elif t == "paragraph_close":
        out.append("\n")

    elif t in ("bullet_list_open", "ordered_list_open"):
        pass

    elif t in ("bullet_list_close", "ordered_list_close"):
        out.append("\n")

    elif t == "list_item_open":
        out.append("• ")

    elif t == "list_item_close":
        out.append("\n")

    elif t == "heading_open":
        out.append("<b>")

    elif t == "heading_close":
        out.append("</b>\n")

    elif t == "strong_open":
        out.append("<b>")

    elif t == "strong_close":
        out.append("</b>")

    elif t == "em_open":
        out.append("<i>")

    elif t == "em_close":
        out.append("</i>")

    elif t == "s_open":
        out.append("<s>")

    elif t == "s_close":
        out.append("</s>")

    elif t == "code_inline":
        out.append(f"<code>{html.escape(token.content)}</code>")

    elif t == "fence":
        lang = token.info.strip() if token.info else ""
        if lang:
            out.append(
                f'<pre><code class="{html.escape(lang)}">'
                f'{html.escape(token.content)}</code></pre>\n'
            )
        else:
            out.append(f"<pre>{html.escape(token.content)}</pre>\n")

    elif t == "code_block":
        out.append(f"<pre>{html.escape(token.content)}</pre>\n")

    elif t == "link_open":
        attrs = token.attrs or {}
        if isinstance(attrs, dict):
            href = html.escape(str(attrs.get("href", "")))
        else:
            # Fallback for older markdown-it-py returning list of [key, value] pairs
            href = ""
            for attr in attrs:
                if attr[0] == "href":
                    href = html.escape(str(attr[1]))
        out.append(f'<a href="{href}">')

    elif t == "link_close":
        out.append("</a>")

    elif t == "softbreak":
        out.append("\n")

    elif t == "hardbreak":
        out.append("\n")

    elif t == "hr":
        out.append("──────────\n")

    elif t == "text":
        out.append(html.escape(token.content))

    elif t == "html_inline":
        # Pass through only safe Telegram tags, escape everything else
        safe = {
            "<b>", "</b>", "<i>", "</i>", "<u>", "</u>",
            "<s>", "</s>", "<code>", "</code>",
        }
        if token.content.strip() in safe:
            out.append(token.content)
        else:
            out.append(html.escape(token.content))

    elif t == "blockquote_open":
        out.append("<blockquote>")

    elif t == "blockquote_close":
        out.append("</blockquote>\n")

    elif t == "html_block":
        # Escape raw HTML blocks — Telegram does not support arbitrary HTML
        out.append(html.escape(token.content))

    elif hasattr(token, "children") and token.children:
        # Unknown token types with children: recurse
        for child in token.children:
            _render_token(child, out)

    # All other token types (images, tables, etc.) are silently skipped
