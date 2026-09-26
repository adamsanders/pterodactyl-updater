import html
import re
from markupsafe import Markup


def discord_markdown(text: str) -> Markup:
  """Converts Discord-flavored markdown into safe HTML."""
  if not text:
    return Markup("")

  safe = html.escape(text)

  # Markdown Links: [label](url)
  safe = re.sub(
      r"\[(.*?)\]\((https?://[^\s\)]+)\)",
      r'<a href="\2" target="_blank" rel="noopener noreferrer"'
      r' class="text-blue-400 hover:underline break-all">\1</a>',
      safe,
  )

  # Headings: ### Header
  safe = re.sub(
      r"(?m)^###\s+(.*?)$",
      r'<h4 class="font-bold text-white text-sm mt-3 mb-1">\1</h4>',
      safe,
  )

  # Bold: **text**
  safe = re.sub(
      r"\*\*(.*?)\*\*",
      r'<strong class="font-semibold text-white">\1</strong>',
      safe,
  )

  # Underline: __text__
  safe = re.sub(r"__(.*?)__", r'<span class="underline">\1</span>', safe)

  # Strikethrough: ~~text~~
  safe = re.sub(
      r"~~(.*?)~~", r'<span class="line-through text-gray-400">\1</span>', safe
  )

  # Bullets: * or •
  safe = re.sub(
      r"(?m)^[\*\•]\s+(.*?)$",
      r'<div class="flex items-start gap-2 ml-1 my-0.5"><span'
      r' class="text-gray-400 select-none">•</span><span'
      r' class="flex-1">\1</span></div>',
      safe,
  )

  # Italics: *text*
  safe = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<em>\1</em>", safe)

  # Line breaks
  safe = safe.replace("\n", "<br>")
  safe = re.sub(r"(</div>|<h4[^>]*>.*?</h4>)<br>", r"\1", safe)
  safe = re.sub(r"(<br\s*/?>){3,}", "<br><br>", safe)

  return Markup(safe)