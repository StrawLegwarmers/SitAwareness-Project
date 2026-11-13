"""The look from update 15: label font stored with the site, quiet sidebar, the new story card."""
import re

from config import ROOT

JS = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "site" / "assets" / "style.css").read_text(encoding="utf-8")


def test_the_label_font_is_stored_with_the_site_and_licensed():
    fonts = ROOT / "site" / "assets" / "fonts"
    for f in re.findall(r'url\("fonts/([^"]+)"\)', CSS):
        assert (fonts / f).stat().st_size > 10_000, f
    assert (fonts / "IBM-Plex-Sans-OFL.txt").read_text().count("SIL Open Font License") >= 1
    assert "IBM Plex Sans" in (ROOT / "NOTICE.md").read_text()
    assert "fonts.googleapis" not in CSS and "fonts.gstatic" not in CSS        # the security policy allows our own fonts only


def test_the_sidebar_has_no_counts_and_normal_case_headings():
    side = JS.split("function renderSidebar()")[1].split("\nfunction ")[0]
    assert 'class="n"' not in side and "toUpperCase" not in side
    assert ">Yours<" in side and ">Reference<" in side
    assert "toUpperCase" not in JS.split("function renderPage(")[1].split("<h1>")[0]      # the page line too


def test_the_story_card_keeps_only_what_was_agreed():
    card = JS.split("function card(s, day, showGroup)")[1].split("\nfunction ")[0]
    for part in ('class="wider"', 'class="status', 'class="card-rule"', 'class="more-toggle"', 'aria-label="Copy with sources"'):
        assert part in card, part
    assert "countryLine(" not in card and "regions</span>" not in card and "<details" not in card
    assert "--status-updated: #1F6FB2" in CSS and "--status-updated: #6CB4EE" in CSS      # Updated in sky blue


def test_the_card_footer_stays_on_one_line_and_uses_region_codes():
    assert ".card-foot > span { flex: 1" not in CSS                      # squeezed "Middle / East &..." into a column
    assert ".card-foot .foot-text { flex: 1; min-width: 0;" in CSS          # the text wraps as one block, copy stays right
    assert ".card.compact .card-foot { position: absolute" not in CSS
    import yaml
    groups = yaml.safe_load((ROOT / "config" / "geo" / "site.yaml").read_text())["groups"]
    assert {g["id"]: g["short"] for g in groups} == {"namerica": "NA", "latam": "LATAM", "europe": "EU", "mena": "MENA",
                                                     "africa": "AFR", "asia": "APAC", "global": "GLOBAL"}
    assert "g.short || g.name" in JS
