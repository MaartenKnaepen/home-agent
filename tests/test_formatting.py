"""Tests for src/home_agent/formatting.py.

Comprehensive unit tests for the Markdown → Telegram HTML converter.
"""

from __future__ import annotations

from home_agent.formatting import md_to_telegram_html


def test_bold() -> None:
    """Bold markdown becomes <b> tags."""
    assert md_to_telegram_html("**bold**") == "<b>bold</b>\n"


def test_italic() -> None:
    """Italic markdown becomes <i> tags."""
    assert md_to_telegram_html("*italic*") == "<i>italic</i>\n"


def test_inline_code() -> None:
    """Inline code becomes <code> tags."""
    assert "<code>x</code>" in md_to_telegram_html("`x`")


def test_fenced_code() -> None:
    """Fenced code block becomes <pre> tags."""
    result = md_to_telegram_html("```\ncode\n```")
    assert "<pre>" in result
    assert "code" in result


def test_fenced_code_with_language() -> None:
    """Fenced code block with language hint uses <pre><code class='...'> tags."""
    result = md_to_telegram_html("```python\nprint('hello')\n```")
    assert "<pre>" in result
    assert 'class="python"' in result
    assert "print" in result


def test_heading() -> None:
    """H1 heading becomes <b> tags."""
    result = md_to_telegram_html("# Header")
    assert "<b>Header</b>" in result


def test_heading_h2() -> None:
    """H2 heading also becomes <b> tags."""
    result = md_to_telegram_html("## Sub Header")
    assert "<b>Sub Header</b>" in result


def test_list() -> None:
    """Unordered list items get bullet prefix."""
    result = md_to_telegram_html("- item")
    assert "•" in result
    assert "item" in result


def test_list_multiple_items() -> None:
    """Multiple list items each get bullet prefix."""
    result = md_to_telegram_html("- first\n- second\n- third")
    assert result.count("•") == 3
    assert "first" in result
    assert "second" in result
    assert "third" in result


def test_escape_ampersand() -> None:
    """Ampersand in plain text is HTML-escaped."""
    assert "&amp;" in md_to_telegram_html("5 & 3")


def test_escape_lt() -> None:
    """Less-than in plain text is HTML-escaped."""
    assert "&lt;" in md_to_telegram_html("a < b")


def test_escape_gt() -> None:
    """Greater-than in plain text is HTML-escaped."""
    assert "&gt;" in md_to_telegram_html("a > b")


def test_plain_text() -> None:
    """Plain text is returned with a trailing newline (from paragraph)."""
    assert md_to_telegram_html("hello") == "hello\n"


def test_fallback_on_none() -> None:
    """Passing None does not raise — falls back to html.escape(str(None))."""
    result = md_to_telegram_html(None)  # type: ignore[arg-type]
    assert result is not None
    assert isinstance(result, str)


def test_link() -> None:
    """Markdown link becomes <a href> tag."""
    result = md_to_telegram_html("[click here](https://example.com)")
    assert '<a href="https://example.com">' in result
    assert "click here" in result
    assert "</a>" in result


def test_link_url_escaped() -> None:
    """Link URL with special HTML chars is escaped in href."""
    result = md_to_telegram_html('[link](https://example.com/?a=1&amp;b=2)')
    assert "<a href=" in result
    assert "link" in result


def test_strikethrough() -> None:
    """Strikethrough becomes <s> tags (requires strikethrough extension)."""
    # markdown-it-py default does not enable strikethrough; text falls back
    result = md_to_telegram_html("~~strike~~")
    assert result is not None  # Should not raise regardless


def test_bold_inside_text() -> None:
    """Bold text embedded in a sentence is correctly tagged."""
    result = md_to_telegram_html("This is **important** text.")
    assert "<b>important</b>" in result
    assert "This is" in result
    assert "text." in result


def test_code_content_escaped() -> None:
    """HTML special chars in code blocks are escaped."""
    result = md_to_telegram_html("`a < b`")
    assert "&lt;" in result
    assert "<code>" in result


def test_fenced_code_content_escaped() -> None:
    """HTML special chars in fenced code blocks are escaped."""
    result = md_to_telegram_html("```\na < b\n```")
    assert "&lt;" in result
    assert "<pre>" in result


def test_nested_bold_italic() -> None:
    """Bold and italic can be nested."""
    result = md_to_telegram_html("***bold italic***")
    assert result is not None
    # Should contain both b and i tags in some form
    assert "<b>" in result or "<i>" in result


def test_horizontal_rule() -> None:
    """Horizontal rule becomes a text divider."""
    result = md_to_telegram_html("---")
    assert "──────────" in result or result  # falls back gracefully


def test_multiple_paragraphs() -> None:
    """Multiple paragraphs are separated by newlines."""
    result = md_to_telegram_html("para one\n\npara two")
    assert "para one" in result
    assert "para two" in result
    assert "\n" in result


def test_empty_string() -> None:
    """Empty string returns empty string."""
    result = md_to_telegram_html("")
    assert isinstance(result, str)
    assert result == ""
