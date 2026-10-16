"""Steam announcement content parser.

Extracts, cleans, and converts Steam BBCode and HTML announcement markup
into normalized Discord-friendly Markdown and extracts banner image URLs.
"""

import html
import re
from typing import Optional

__all__ = ["parse_steam_content"]

STEAM_CLAN_IMAGE_BASE_URL = "https://clan.cloudflare.steamstatic.com/images"

# Image extraction patterns
_BB_IMG_PATTERN = re.compile(r"\[img\](.*?)\[/img\]", re.IGNORECASE)
_HTML_IMG_PATTERN = re.compile(
    r"""<img\s+[^>]*?src\s*=\s*["'](.*?)["']""", re.IGNORECASE
)

# HTML markup conversion patterns
_HTML_A_PATTERN = re.compile(
    r"""<a\s+[^>]*?href\s*=\s*["'](.*?)["'][^>]*?>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_HTML_H_PATTERN = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_HTML_B_PATTERN = re.compile(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", re.IGNORECASE | re.DOTALL)
_HTML_I_PATTERN = re.compile(r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>", re.IGNORECASE | re.DOTALL)
_HTML_STRIKE_PATTERN = re.compile(r"<(?:strike|s|del)[^>]*>(.*?)</(?:strike|s|del)>", re.IGNORECASE | re.DOTALL)
_HTML_LI_PATTERN = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_HTML_BR_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_P_PATTERN = re.compile(r"</p>", re.IGNORECASE)
_HTML_DIV_PATTERN = re.compile(r"</div>", re.IGNORECASE)
_HTML_TAGS_STRIP_PATTERN = re.compile(r"<[^>]+>")

# BBCode markup conversion patterns
_BB_B_PATTERN = re.compile(r"\[b\](.*?)\[/b\]", re.IGNORECASE | re.DOTALL)
_BB_I_PATTERN = re.compile(r"\[i\](.*?)\[/i\]", re.IGNORECASE | re.DOTALL)
_BB_U_PATTERN = re.compile(r"\[u\](.*?)\[/u\]", re.IGNORECASE | re.DOTALL)
_BB_STRIKE_PATTERN = re.compile(r"\[strike\](.*?)\[/strike\]", re.IGNORECASE | re.DOTALL)
_BB_H_PATTERN = re.compile(r"\[h[1-6]\](.*?)\[/h[1-6]\]", re.IGNORECASE | re.DOTALL)
_BB_URL_PATTERN = re.compile(
    r"""\[url=["']?(.*?)["']?\](.*?)\[/url\]""", re.IGNORECASE | re.DOTALL
)
_BB_LIST_PATTERN = re.compile(r"\[/?(?:olist|list)\]", re.IGNORECASE)
_BB_LIST_ITEM_PATTERN = re.compile(r"\[\*\]", re.IGNORECASE)
_BB_IMG_STRIP_PATTERN = re.compile(r"\[img\].*?\[/img\]", re.IGNORECASE | re.DOTALL)
_BB_TAGS_STRIP_PATTERN = re.compile(
    r"\[/?[a-zA-Z0-9_\-=:\.\s\"';,/&]+\](?!\()"
)

# Newline normalization
_EXCESSIVE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


def parse_steam_content(text: Optional[str] = None) -> tuple[str, Optional[str]]:
  """Parses raw Steam announcement text (BBCode/HTML) into clean Markdown.

  Args:
      text: The raw announcement content string from Steam News API.

  Returns:
      A tuple of (cleaned_markdown_text, banner_image_url).
  """
  if not text:
    return "", None

  # Normalize line endings
  text = text.replace("\r\n", "\n").replace("\r", "\n")

  # 1. Extract banner image (check BBCode first, then HTML img)
  image_url: Optional[str] = None
  bb_img = _BB_IMG_PATTERN.search(text)
  if bb_img:
    image_url = bb_img.group(1).strip()
  else:
    html_img = _HTML_IMG_PATTERN.search(text)
    if html_img:
      image_url = html_img.group(1).strip()

  if image_url and "{STEAM_CLAN_IMAGE}" in image_url:
    image_url = image_url.replace("{STEAM_CLAN_IMAGE}", STEAM_CLAN_IMAGE_BASE_URL)

  # 2. Transform HTML tags to Markdown
  text = _HTML_A_PATTERN.sub(r"[\2](\1)", text)
  text = _HTML_H_PATTERN.sub(r"\n### \1\n", text)
  text = _HTML_B_PATTERN.sub(r"**\1**", text)
  text = _HTML_I_PATTERN.sub(r"*\1*", text)
  text = _HTML_STRIKE_PATTERN.sub(r"~~\1~~", text)
  text = _HTML_LI_PATTERN.sub(r"• \1\n", text)
  text = _HTML_BR_PATTERN.sub(r"\n", text)
  text = _HTML_P_PATTERN.sub(r"\n\n", text)
  text = _HTML_DIV_PATTERN.sub(r"\n", text)
  text = _HTML_TAGS_STRIP_PATTERN.sub("", text)

  # 3. Transform Steam BBCode tags to Markdown
  text = _BB_B_PATTERN.sub(r"**\1**", text)
  text = _BB_I_PATTERN.sub(r"*\1*", text)
  text = _BB_U_PATTERN.sub(r"__\1__", text)
  text = _BB_STRIKE_PATTERN.sub(r"~~\1~~", text)
  text = _BB_H_PATTERN.sub(r"\n### \1\n", text)
  text = _BB_URL_PATTERN.sub(r"[\2](\1)", text)
  text = _BB_LIST_PATTERN.sub("", text)
  text = _BB_LIST_ITEM_PATTERN.sub("• ", text)
  text = _BB_IMG_STRIP_PATTERN.sub("", text)
  text = _BB_TAGS_STRIP_PATTERN.sub("", text)

  # 4. Unescape HTML entities and normalize whitespace
  text = html.unescape(text)
  cleaned = "\n".join([line.strip() for line in text.split("\n")])
  return _EXCESSIVE_NEWLINES_PATTERN.sub("\n\n", cleaned).strip(), image_url
