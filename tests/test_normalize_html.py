"""Sanitisation et double-encodage d'entites."""

from __future__ import annotations

import pytest

from conftest import NOW, read_fixture
from veille.ingest.parse import parse_feed
from veille.normalize.html import sanitize, strip_tags, unescape_escaped_markup
from veille.normalize.text import clean_title, content_hash, fix_double_escaping, normalize_ws

HOSTILE = (
    "<p>Bonjour<!-- commentaire cache --></p>"
    '<script>alert("xss")</script>'
    '<img src=x onerror="alert(1)">'
    '<a href="javascript:alert(2)">clic</a>'
    '<iframe src="https://evil.example"></iframe>'
    '<div style="position:fixed">bloc</div>'
)


def test_sanitize_removes_script_onerror_and_comments() -> None:
    cleaned = sanitize(HOSTILE)
    assert cleaned is not None
    lowered = cleaned.lower()
    assert "<script" not in lowered
    assert "alert(" not in lowered
    assert "onerror" not in lowered
    assert "<!--" not in lowered
    assert "commentaire cache" not in lowered
    assert "<img" not in lowered
    assert "<iframe" not in lowered
    assert "javascript:" not in lowered
    # le texte legitime survit
    assert "Bonjour" in cleaned


def test_sanitize_keeps_allowlisted_markup_and_adds_rel() -> None:
    cleaned = sanitize('<p>Voir <a href="https://example.com/a">la source</a>.</p>')
    assert cleaned is not None
    assert "<p>" in cleaned
    assert 'href="https://example.com/a"' in cleaned
    assert "noopener" in cleaned and "noreferrer" in cleaned


def test_sanitize_returns_none_when_nothing_displayable_remains() -> None:
    """Les items Hacker News n'ont pas toujours de resume exploitable."""
    assert sanitize(None) is None
    assert sanitize("") is None
    assert sanitize("   \n  ") is None
    assert sanitize("<script>alert(1)</script>") is None
    assert sanitize("<p>   </p>") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("&amp;eacute;", "&eacute;"),
        ("&amp;#233;", "&#233;"),
        ("&amp;#x00E9;", "&#x00E9;"),
        ("&amp;amp;eacute;", "&eacute;"),
        # un & seul echappe reste echappe : ce n'est pas du double-encodage
        ("Fnac &amp; Darty", "Fnac &amp; Darty"),
        # et surtout : on ne reintroduit pas de balise
        ("&amp;lt;script&amp;gt;", "&lt;script&gt;"),
    ],
)
def test_fix_double_escaping(raw: str, expected: str) -> None:
    assert fix_double_escaping(raw) == expected


def test_double_escaped_entity_never_reaches_the_template() -> None:
    cleaned = sanitize("<p>Cybers&amp;eacute;curit&amp;eacute; renforc&amp;eacute;e</p>")
    assert cleaned is not None
    assert "&amp;eacute;" not in cleaned
    assert "Cybersécurité renforcée" in strip_tags(cleaned)


def test_double_escaped_tag_stays_inert_after_sanitize() -> None:
    cleaned = sanitize("<p>&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;</p>")
    assert cleaned is not None
    assert "<script" not in cleaned.lower()


def test_clean_title_unescapes_and_collapses_whitespace() -> None:
    assert clean_title("  Cybers&amp;eacute;curit&amp;eacute;\n  renforc&eacute;e ") == (
        "Cybersécurité renforcée"
    )


def test_strip_tags() -> None:
    assert strip_tags("<p>a <strong>b</strong>  c</p>") == "a b c"
    assert strip_tags(None) == ""
    assert strip_tags("") == ""


def test_strip_tags_returns_real_text_not_escaped_html() -> None:
    """nh3 echappe le texte qu'il conserve : sans desechappement, la page
    afficherait `&amp;` et `&nbsp;` en toutes lettres."""
    assert strip_tags("<p>Python &amp; JavaScript</p>") == "Python & JavaScript"
    assert strip_tags("<p>Fnac & Darty</p>") == "Fnac & Darty"
    assert "&nbsp;" not in strip_tags("<p>il y&nbsp;a</p>")
    assert "&" not in strip_tags("<p>&laquo; cite &raquo;</p>")


def test_normalize_ws() -> None:
    assert normalize_ws("  a \n\t b  ") == "a b"


def test_content_hash_is_stable_and_sensitive() -> None:
    a = content_hash("Titre", "resume")
    assert a == content_hash("  Titre  ", "resume\n")
    assert len(a) == 64
    assert a != content_hash("Titre", "resume modifie")
    assert a != content_hash("Titre modifie", "resume")


def test_content_hash_separator_prevents_collisions() -> None:
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_content_hash_ignores_cosmetic_markup_changes() -> None:
    """Le hash porte sur le texte : rebalisage != revision."""
    first = content_hash("Titre", strip_tags("<p>Un <b>resume</b></p>"))
    second = content_hash("Titre", strip_tags("<div>Un <strong>resume</strong></div>"))
    assert first == second


# ------------------------------------------------ HTML livre echappe (LeMagIT)

ESCAPED_ARTICLE = (
    "&lt;p&gt;Premier paragraphe.&lt;/p&gt; \n"
    '&lt;p&gt;Voir &lt;a href="https://example.com/a"&gt;la source&lt;/a&gt;, '
    "Junie&amp;nbsp;CLI.&lt;/p&gt;"
)


def test_escaped_html_summary_is_restored_then_sanitized() -> None:
    cleaned = sanitize(ESCAPED_ARTICLE)
    assert cleaned is not None
    assert "<p>" in cleaned, "le balisage echappe redevient du balisage"
    assert 'href="https://example.com/a"' in cleaned
    assert "noopener" in cleaned, "et passe par nh3 comme n'importe quel lien"
    text = strip_tags(cleaned)
    assert "<p>" not in text and "&lt;" not in text
    assert text.startswith("Premier paragraphe. Voir la source, Junie")
    assert "&nbsp;" not in text


def test_escaped_script_is_removed_by_nh3_not_displayed() -> None:
    """Desechapper reintroduit `<script>` : c'est nh3 qui doit le retirer, et la
    charge ne doit survivre sous AUCUNE forme, pas meme comme texte visible."""
    raw = (
        "&lt;p&gt;Texte légitime.&lt;/p&gt;"
        "&lt;script&gt;alert('xss')&lt;/script&gt;"
        '&lt;img src="x" onerror="alert(1)"&gt;'
        '&lt;a href="javascript:alert(2)"&gt;clic&lt;/a&gt;'
    )
    cleaned = sanitize(raw)
    assert cleaned is not None
    lowered = cleaned.lower()
    for needle in ("script", "alert(", "onerror", "javascript:", "<img", "&lt;"):
        assert needle not in lowered, needle
    assert strip_tags(cleaned) == "Texte légitime.clic"


@pytest.mark.parametrize(
    "raw",
    [
        # texte brut qui cite des comparaisons : aucune balise echappee
        "Affected versions are &lt; 0.6.2 and &gt;= 0.5.0.",
        # vrai HTML qui PARLE de HTML : les entites sont le contenu
        "<p>Au-dela d'un simple <code>&lt;circle&gt;</code>.</p>",
        "<p>&lt;p&gt;cite&lt;/p&gt;</p>",
        # charge citee en texte par un article de securite, sans structure
        "La charge &lt;script&gt;alert(1)&lt;/script&gt; passe le filtre.",
        # balise de structure echappee, mais pas en tete de resume
        "Utiliser &lt;p&gt;texte&lt;/p&gt; pour un paragraphe.",
        # ouverte en tete mais jamais refermee (resume tronque)
        "&lt;p&gt;Resume tronque sans fermeture",
    ],
)
def test_text_that_merely_mentions_html_is_left_escaped(raw: str) -> None:
    assert unescape_escaped_markup(raw) == raw


def test_escaped_body_fixture_end_to_end() -> None:
    """Le flux reel : <body> non standard, que feedparser rend en entites."""
    parsed = parse_feed(read_fixture("escaped_body.xml"), fetched_at=NOW)
    by_url = {entry.url_canonical: entry for entry in parsed.entries}

    article = by_url["https://exemple-echappe.test/actualites/jetbrains-air"]
    assert article.raw_summary is not None
    assert article.raw_summary.startswith("&lt;p&gt;"), "le brut reste tel que livre"
    assert article.summary_clean is not None
    clean = article.summary_clean.lower()
    assert "<p>" in clean
    for needle in ("script", "alert(", "onerror", "<img", "&lt;"):
        assert needle not in clean, needle
    text = strip_tags(article.summary_clean)
    assert text.startswith("Jetbrains tente de prendre de la hauteur. L")
    assert "éditeur connu pour ses IDE a lancé Junie" in text
    assert "Air devient une suite" in text
    assert article.content_hash == content_hash(article.title, text)

    plain = by_url["https://exemple-echappe.test/actualites/texte-brut"]
    assert strip_tags(plain.summary_clean) == "Affected versions are < 0.6.2 and >= 0.5.0."
