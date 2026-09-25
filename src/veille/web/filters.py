"""Filtres Jinja. La conversion UTC -> Europe/Paris se fait ICI et nulle part
ailleurs : la base ne contient que de l'UTC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from veille.normalize.html import strip_tags

PARIS = ZoneInfo("Europe/Paris")

LANG_LABELS = {"fr": "FR", "en": "EN"}
TOPIC_LABELS = {"ai": "IA", "sec": "Cyber", "both": "IA + Cyber"}
SOURCE_LABELS = {
    "media": "média",
    "vendor": "éditeur",
    "official": "officiel",
    "community": "communauté",
}


def to_paris(value: datetime) -> datetime:
    return value.astimezone(PARIS)


def datetime_attr(value: datetime) -> str:
    """Valeur de l'attribut datetime= d'un <time>, en ISO 8601 local."""
    return to_paris(value).isoformat(timespec="minutes")


def absolute_date(value: datetime) -> str:
    return to_paris(value).strftime("%d/%m/%Y %H:%M")


#: En dur plutot que via locale : setlocale depend de l'image et du poste, et
#: une page qui passe a "Thursday" selon la machine n'est pas une page fiable.
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _as_paris_date(value: datetime | date) -> date:
    return to_paris(value).date() if isinstance(value, datetime) else value


def day_label(value: datetime | date) -> str:
    """Date longue en francais, ex. "jeudi 25 septembre 2026", jour de Paris."""
    day = _as_paris_date(value)
    first = "1er" if day.day == 1 else str(day.day)
    return f"{WEEKDAYS[day.weekday()]} {first} {MONTHS[day.month - 1]} {day.year}"


def day_heading(value: datetime | date, now: datetime | None = None) -> str:
    """Titre de rubrique du journal : "Aujourd'hui", "Hier", sinon la date."""
    day = _as_paris_date(value)
    today = to_paris(now or datetime.now(tz=UTC)).date()
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    return day_label(day).capitalize()


def time_of_day(value: datetime) -> str:
    """Heure a la francaise, ex. "14h05"."""
    return to_paris(value).strftime("%Hh%M")


def by_day(rows: Iterable[Any]) -> list[tuple[date, list[Any]]]:
    """Regroupe des ArticleRow deja tries par jour de publication, heure de Paris.

    Preserve l'ordre : la requete trie deja par published_at decroissant, un tri
    ici masquerait une regression de la requete au lieu de la montrer. Un
    article publie a 23h30 UTC en ete appartient au lendemain parisien : c'est
    la date que le lecteur a vecue qui compte, pas celle du serveur.
    """
    groups: list[tuple[date, list[Any]]] = []
    for row in rows:
        day = to_paris(row.article.published_at).date()
        if groups and groups[-1][0] == day:
            groups[-1][1].append(row)
        else:
            groups.append((day, [row]))
    return groups


def relative_date(value: datetime, now: datetime | None = None) -> str:
    """Date relative en francais. `now` est injectable pour les tests."""
    now = now or datetime.now(tz=UTC)
    seconds = (now - value.astimezone(UTC)).total_seconds()

    if seconds < 0:
        return "à l'instant"
    minutes = seconds / 60
    if minutes < 1:
        return "à l'instant"
    if minutes < 60:
        return f"il y a {int(minutes)} min"
    hours = minutes / 60
    if hours < 24:
        return f"il y a {int(hours)} h"
    days = hours / 24
    if days < 2:
        return "hier"
    if days < 7:
        return f"il y a {int(days)} jours"
    if days < 60:
        return f"il y a {int(days / 7)} sem."
    return absolute_date(value)


def excerpt(value: str | None, length: int = 240) -> str:
    """Extrait en texte brut du resume nettoye.

    Le rendu ne fait PAS confiance au HTML de flux : meme apres nh3, aucun
    `|safe` n'est applique a du contenu de flux dans les templates. On affiche
    donc le texte, echappe par Jinja comme le reste.
    """
    text = strip_tags(value)
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "…"


#: Prefixe du message -> nature de la panne. Le pipeline ecrit
#: "<NomDException>: <message>" precisement pour rendre ce tri possible.
ERROR_KINDS: dict[str, str] = {
    "FetchError": "reseau",
    "FeedParseError": "flux",
    "InvalidUrlError": "flux",
    "VeilleError": "flux",
}

ERROR_KIND_LABELS = {
    "reseau": "réseau",
    "flux": "flux",
    "interne": "interne",
}


def error_kind(message: str | None) -> str:
    """'reseau' | 'flux' | 'interne' | ''.

    Une panne reseau est transitoire et attendue (hnrss tombe regulierement) ;
    un flux illisible demande une action. Les afficher de la meme couleur revient
    a n'en afficher aucune.
    """
    if not message:
        return ""
    name = message.split(":", 1)[0].strip()
    if name in ERROR_KINDS:
        return ERROR_KINDS[name]
    return "interne" if name.endswith("Error") else ""


def error_kind_label(message: str | None) -> str:
    return ERROR_KIND_LABELS.get(error_kind(message), "")


GAP_LABELS = {
    "none": "aucun trou",
    "suspected": "trou suspecte",
    "unknown": "indetermine",
}


def gap_label(value: str | None) -> str:
    return GAP_LABELS.get(value or "", "")


def duration(value: timedelta | None) -> str:
    """Duree lisible. Rend "-" pour None : une mesure absente ne doit pas
    s'afficher comme une mesure nulle."""
    if value is None:
        return "—"
    seconds = int(value.total_seconds())
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} h".replace(".0 ", " ")
    return f"{hours / 24:.1f} j".replace(".0 ", " ")


def lang_label(value: str) -> str:
    return LANG_LABELS.get(value, value.upper())


def topic_label(value: str) -> str:
    return TOPIC_LABELS.get(value, value)


def source_label(value: str) -> str:
    return SOURCE_LABELS.get(value, value)


FILTERS = {
    "to_paris": to_paris,
    "datetime_attr": datetime_attr,
    "absolute_date": absolute_date,
    "relative_date": relative_date,
    "day_label": day_label,
    "day_heading": day_heading,
    "time_of_day": time_of_day,
    "by_day": by_day,
    "duration": duration,
    "gap_label": gap_label,
    "error_kind": error_kind,
    "error_kind_label": error_kind_label,
    "excerpt": excerpt,
    "lang_label": lang_label,
    "topic_label": topic_label,
    "source_label": source_label,
}
