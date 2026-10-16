import unittest

from app.adapters.steam_content_parser import (
    STEAM_CLAN_IMAGE_BASE_URL,
    parse_steam_content,
)


class TestSteamContentParser(unittest.TestCase):

  def test_clean_content_bbcode_formatting(self):
    bbcode = (
        "[b]Bold Announcement[/b]\n"
        "[i]Italic notes[/i]\n"
        "[u]Underlined text[/u]\n"
        "[strike]Obsolete build[/strike]\n"
        "[h2]Patch 1.2 Notes[/h2]\n"
        "[url=https://store.steampowered.com]Steam Store[/url]\n"
        "[list][*]Fixed bug 1[*]Fixed bug 2[/list]"
    )
    cleaned, img = parse_steam_content(bbcode)
    self.assertIn("**Bold Announcement**", cleaned)
    self.assertIn("*Italic notes*", cleaned)
    self.assertIn("__Underlined text__", cleaned)
    self.assertIn("~~Obsolete build~~", cleaned)
    self.assertIn("### Patch 1.2 Notes", cleaned)
    self.assertIn("[Steam Store](https://store.steampowered.com)", cleaned)
    self.assertIn("• Fixed bug 1", cleaned)
    self.assertIn("• Fixed bug 2", cleaned)
    self.assertIsNone(img)

  def test_clean_content_html_formatting(self):
    raw_html = (
        "<b>Important Update</b><br>"
        "<i>Performance fixes</i><br>"
        "<s>Deprecated feature</s><br>"
        "<h4>Changelog</h4>"
        "<a href='https://example.com'>Details</a>"
        "<ul><li>Server stability improvements</li></ul>"
    )
    cleaned, img = parse_steam_content(raw_html)
    self.assertIn("**Important Update**", cleaned)
    self.assertIn("*Performance fixes*", cleaned)
    self.assertIn("~~Deprecated feature~~", cleaned)
    self.assertIn("### Changelog", cleaned)
    self.assertIn("[Details](https://example.com)", cleaned)
    self.assertIn("• Server stability improvements", cleaned)

  def test_clean_content_steam_clan_image_replacement(self):
    text_with_bb_img = (
        "[img]{STEAM_CLAN_IMAGE}/12345/hero.png[/img]\nMajor Content Release!"
    )
    cleaned, img = parse_steam_content(text_with_bb_img)
    self.assertEqual(
        img, f"{STEAM_CLAN_IMAGE_BASE_URL}/12345/hero.png"
    )
    self.assertIn("Major Content Release!", cleaned)
    self.assertNotIn("[img]", cleaned)

    text_with_html_img = (
        "<img src='https://cdn.akamai.steamstatic.com/banner.jpg'><p>Notes</p>"
    )
    cleaned2, img2 = parse_steam_content(text_with_html_img)
    self.assertEqual(img2, "https://cdn.akamai.steamstatic.com/banner.jpg")

  def test_clean_content_html_entities_and_excessive_whitespace(self):
    text = (
        "Items &amp; Inventory &mdash; &quot;Quests&#39;&quot;\n\n\n\n\nFixed"
        " balance."
    )
    cleaned, _ = parse_steam_content(text)
    self.assertIn("Items & Inventory — \"Quests'\"", cleaned)
    self.assertNotIn("\n\n\n", cleaned)

  def test_empty_and_none_input(self):
    self.assertEqual(parse_steam_content(""), ("", None))
    self.assertEqual(parse_steam_content(None), ("", None))

  def test_whitespace_only_input(self):
    self.assertEqual(parse_steam_content("   \n\t\n   "), ("", None))

  def test_heading_levels(self):
    for i in range(1, 7):
      cleaned_bb, _ = parse_steam_content(f"[h{i}]Heading {i}[/h{i}]")
      self.assertEqual(cleaned_bb, f"### Heading {i}")

      cleaned_html, _ = parse_steam_content(f"<h{i}>Heading {i}</h{i}>")
      self.assertEqual(cleaned_html, f"### Heading {i}")

  def test_formatting_variations(self):
    # strong, em, del, strike
    html_sample = (
        "<strong>Strong</strong> <em>Em</em> <del>Del</del> <strike>Strike</strike>"
    )
    cleaned, _ = parse_steam_content(html_sample)
    self.assertEqual(cleaned, "**Strong** *Em* ~~Del~~ ~~Strike~~")

  def test_strip_custom_and_unknown_bbcode_tags(self):
    text = "[quote]Some quote[/quote] [spoiler]Secret info[/spoiler] normal text"
    cleaned, _ = parse_steam_content(text)
    self.assertEqual(cleaned, "Some quote Secret info normal text")

  def test_first_image_captured_and_remaining_stripped(self):
    text = (
        "[img]https://example.com/first.jpg[/img]\n"
        "Middle text\n"
        "[img]https://example.com/second.jpg[/img]"
    )
    cleaned, img = parse_steam_content(text)
    self.assertEqual(img, "https://example.com/first.jpg")
    self.assertEqual(cleaned, "Middle text")
    self.assertNotIn("first.jpg", cleaned)
    self.assertNotIn("second.jpg", cleaned)

  def test_mixed_html_and_bbcode(self):
    text = (
        "<h3>Title</h3>\n"
        "[list][*]<b>Bug 1</b> fixed\n"
        "[*]<i>Bug 2</i> mitigated[/list]\n"
        "<p>Read more at <a href='https://valheimgame.com'>Valheim</a>.</p>"
    )
    cleaned, img = parse_steam_content(text)
    self.assertIn("### Title", cleaned)
    self.assertIn("• **Bug 1** fixed", cleaned)
    self.assertIn("• *Bug 2* mitigated", cleaned)
    self.assertIn("[Valheim](https://valheimgame.com)", cleaned)
    self.assertIsNone(img)

  def test_bbcode_url_with_quotes(self):
    double_quoted = '[url="https://store.steampowered.com/app/10/"]Counter-Strike[/url]'
    cleaned_dq, _ = parse_steam_content(double_quoted)
    self.assertEqual(cleaned_dq, "[Counter-Strike](https://store.steampowered.com/app/10/)")

    single_quoted = "[url='https://valheimgame.com']Valheim Official[/url]"
    cleaned_sq, _ = parse_steam_content(single_quoted)
    self.assertEqual(cleaned_sq, "[Valheim Official](https://valheimgame.com)")

  def test_strip_previewyoutube_and_semicolon_tags(self):
    text = (
        "Check out our new update trailer:\n"
        "[previewyoutube=g_8o5X7z_l4;full][/previewyoutube]\n"
        "[hr][/hr]Stay tuned!"
    )
    cleaned, _ = parse_steam_content(text)
    self.assertEqual(
        cleaned,
        "Check out our new update trailer:\n\nStay tuned!",
    )
    self.assertNotIn("previewyoutube", cleaned)
    self.assertNotIn("hr", cleaned)

  def test_crlf_line_endings_normalization(self):
    text = "Line 1\r\nLine 2\r\n\r\n\r\nLine 3"
    cleaned, _ = parse_steam_content(text)
    self.assertEqual(cleaned, "Line 1\nLine 2\n\nLine 3")

  def test_html_img_with_spaces_and_clan_image(self):
    text = '<img src = "{STEAM_CLAN_IMAGE}/99999/patch_banner.png" alt="banner" />\nChangelog notes'
    cleaned, img = parse_steam_content(text)
    self.assertEqual(
        img,
        f"{STEAM_CLAN_IMAGE_BASE_URL}/99999/patch_banner.png",
    )
    self.assertEqual(cleaned, "Changelog notes")

  def test_ordered_list(self):
    text = "[olist][*]First item[*]Second item[/olist]"
    cleaned, _ = parse_steam_content(text)
    self.assertIn("• First item", cleaned)
    self.assertIn("• Second item", cleaned)
    self.assertNotIn("olist", cleaned)

  def test_enshrouded_bbcode_list_with_paragraphs_and_close_item_tags(self):
    raw = (
        "[h2]Changelog[/h2]"
        "[list][*][p]Fixed an issue that prevented configuring world settings.[/p][/*]"
        "[*][p]Fixed a rare crash during save game migration.[/p][/*]"
        "[*][p]Fixed a strange-looking rendering issue.[/p][/*][/list]"
    )
    cleaned, _ = parse_steam_content(raw)
    self.assertIn("### Changelog", cleaned)
    self.assertIn("• Fixed an issue that prevented configuring world settings.", cleaned)
    self.assertIn("• Fixed a rare crash during save game migration.", cleaned)
    self.assertIn("• Fixed a strange-looking rendering issue.", cleaned)
    self.assertNotIn("[/*]", cleaned)
    self.assertNotIn("[/]", cleaned)
    self.assertNotIn("[p]", cleaned)
    self.assertNotIn("[/p]", cleaned)
    lines = [l for l in cleaned.splitlines() if l.startswith("• ")]
    self.assertEqual(len(lines), 3)

  def test_anonymous_closing_tags_and_empty_tags_stripped(self):
    raw = "Item 1[/]• Item 2[] [/*]done"
    cleaned, _ = parse_steam_content(raw)
    self.assertEqual(cleaned, "Item 1• Item 2 done")

  def test_list_items_on_separate_lines_without_rogue_asterisks(self):
    raw = "[list][*]First fix[/*][*]Second fix[/*][/list]"
    cleaned, _ = parse_steam_content(raw)
    self.assertNotIn("[/*]", cleaned)
    lines = cleaned.splitlines()
    self.assertEqual(lines, ["• First fix", "• Second fix"])


if __name__ == "__main__":
  unittest.main()
