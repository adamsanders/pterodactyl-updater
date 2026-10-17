import unittest
from markupsafe import Markup

from app.web.filters import discord_markdown


class TestDiscordMarkdownFilter(unittest.TestCase):

  def test_empty_and_none_text(self):
    self.assertEqual(discord_markdown(""), Markup(""))
    self.assertEqual(discord_markdown(None), Markup(""))

  def test_raw_html_is_escaped(self):
    text = "<script>alert('pwned')</script> & <b>test</b>"
    result = str(discord_markdown(text))
    self.assertNotIn("<script>", result)
    self.assertNotIn("<b>", result)
    self.assertIn("&lt;script&gt;", result)
    self.assertIn("&lt;b&gt;test&lt;/b&gt;", result)

  def test_markdown_bold_and_italic(self):
    text = "**bold text** and *italic text*"
    result = str(discord_markdown(text))
    self.assertIn('<strong class="font-semibold text-white">bold text</strong>', result)
    self.assertIn("<em>italic text</em>", result)

  def test_markdown_underline_and_strikethrough(self):
    text = "__underlined__ and ~~struck~~"
    result = str(discord_markdown(text))
    self.assertIn('<span class="underline">underlined</span>', result)
    self.assertIn('<span class="line-through text-gray-400">struck</span>', result)

  def test_markdown_links(self):
    text = "Visit [Valheim Discord](https://discord.gg/valheim) for help."
    result = str(discord_markdown(text))
    self.assertIn(
        '<a href="https://discord.gg/valheim" target="_blank" rel="noopener noreferrer"'
        ' class="text-blue-400 hover:underline break-all">Valheim Discord</a>',
        result,
    )

  def test_markdown_headings(self):
    text = "### Patch 0.218 Notes"
    result = str(discord_markdown(text))
    self.assertIn('<h4 class="font-bold text-white text-sm mt-3 mb-1">Patch 0.218 Notes</h4>', result)

  def test_markdown_bullet_points(self):
    text = "* First fix\n• Second fix"
    result = str(discord_markdown(text))
    self.assertIn('<div class="flex items-start gap-2 ml-1 my-0.5"><span class="text-gray-400 select-none">•</span><span class="flex-1">First fix</span></div>', result)
    self.assertIn('<div class="flex items-start gap-2 ml-1 my-0.5"><span class="text-gray-400 select-none">•</span><span class="flex-1">Second fix</span></div>', result)


if __name__ == "__main__":
  unittest.main()
