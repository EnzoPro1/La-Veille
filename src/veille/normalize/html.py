"""Sanitisation du HTML de flux.

Le HTML des flux est du contenu non fiable. `raw_summary` conserve l'original
pour audit, `summary_clean` est la seule valeur que les templates ont le droit
d'afficher, et aucun `|safe` ne doit apparaitre ailleurs que sur cette colonne.
"""

from __future__ import annotations

import html
import re

import nh3

from veille.normalize.text import fix_double_escaping, normalize_ws, unescape_text

#: Allowlist stricte : mise en forme minimale, aucun media, aucun conteneur
#: exploitable pour du CSS d'exfiltration. Ni <img>, ni <iframe>, ni <style>.
ALLOWED_TAGS: set[str] = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "title"}}

ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto"}

LINK_REL = "noopener noreferrer nofollow"

#: Balises de structure. Un resume qui en OUVRE une, echappee, des son premier
#: caractere et en referme une autre plus loin est du HTML livre comme texte :
#: LeMagIT publie l'article entier dans un <body> non standard, echappe une
#: fois, et feedparser le rend tel quel en entites.
_BLOCK_TAGS = r"(?:p|div|section|article|blockquote|pre|ul|ol|li|h[1-6]|figure|table)"
_ESCAPED_BLOCK_OPEN_RE = re.compile(rf"\A\s*&lt;{_BLOCK_TAGS}(?:\s[^<>]*?)?&gt;", re.IGNORECASE)
_ESCAPED_BLOCK_CLOSE_RE = re.compile(rf"&lt;/{_BLOCK_TAGS}\s*&gt;", re.IGNORECASE)
_REAL_TAG_RE = re.compile(r"<[a-zA-Z/!?]")


def unescape_escaped_markup(raw: str) -> str:
    """Retire UN niveau d'echappement a un resume qui n'est que du HTML echappe.

    Ce desechappement reintroduit des balises, y compris `<script>` si le flux
    en a echappe un : c'est voulu, et c'est pourquoi il a lieu AVANT nh3, jamais
    apres. nh3 reste ce qui retire script/onerror/javascript:, exactement comme
    pour un flux qui livrerait ces balises en clair.

    Le critere est etroit a dessein, pour ne pas toucher a du texte qui PARLE de
    HTML ("Affected versions are &lt; 0.6.2", un `<code>&lt;circle&gt;</code>`,
    une charge XSS citee dans un article de securite) :
    - aucune vraie balise : un resume en HTML reel qui contient des entites
      les contient pour de bonnes raisons ;
    - une balise de structure echappee en TOUT debut de resume ;
    - au moins une balise de structure echappee refermee.
    """
    if _REAL_TAG_RE.search(raw):
        return raw
    if not _ESCAPED_BLOCK_OPEN_RE.match(raw) or not _ESCAPED_BLOCK_CLOSE_RE.search(raw):
        return raw
    # Un seul niveau : `&amp;lt;` devient `&lt;`, soit un "<" litteral dans le
    # HTML restitue, ce que l'auteur avait ecrit.
    return html.unescape(raw)


def sanitize(raw: str | None) -> str | None:
    """Renvoie le HTML nettoye, ou None s'il ne reste rien d'affichable.

    Renvoyer None plutot qu'une chaine vide est deliberé : le template teste
    l'absence de resume, il ne doit pas avoir a distinguer None de "" ni de
    "<p></p>" (les items Hacker News sont concernes).
    """
    if raw is None:
        return None
    prepared = fix_double_escaping(unescape_escaped_markup(raw))
    if not prepared.strip():
        return None

    cleaned = nh3.clean(
        prepared,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel=LINK_REL,
        strip_comments=True,
    ).strip()

    if not cleaned or not strip_tags(cleaned):
        return None
    return cleaned


def strip_tags(value: str | None) -> str:
    """Texte brut d'un fragment HTML, blancs normalises.

    nh3 produit du HTML : en retirant les balises il ECHAPPE le texte restant
    (`&` devient `&amp;`, l'insecable devient `&nbsp;`). Sans le desechappement
    final, Jinja echapperait une seconde fois et la page afficherait `&amp;` en
    toutes lettres. La sortie est du texte, jamais reinjectee comme du balisage :
    elle alimente le hash de contenu et l'extrait, tous deux echappes au rendu.
    """
    if not value:
        return ""
    stripped = nh3.clean(value, tags=set(), attributes={}, strip_comments=True)
    return normalize_ws(unescape_text(stripped))
