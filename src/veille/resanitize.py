"""Reapplique la normalisation actuelle aux articles deja stockes.

`raw_summary` est conserve tel que livre precisement pour ca : quand la
sanitisation change (HTML livre echappe par LeMagIT, par exemple), les articles
qui ont deja quitte la page courante du flux ne repasseront jamais par
l'ingestion. Seul ce recalcul les corrige.

Recalcule `summary_clean` ET `content_hash` : le hash porte sur le texte du
resume nettoye. Laisser l'ancien ferait prendre la correction pour une revision
de l'article au prochain passage du flux.

`updated_at` n'est PAS touche : il date une revision par la source, et une
normalisation rejouee n'en est pas une. `first_seen_at`, `published_at` et
`last_seen_at` non plus, pour la meme raison.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from veille.errors import IngestLockedError
from veille.ingest.lock import advisory_lock
from veille.models import Article, Feed
from veille.normalize.html import sanitize, strip_tags
from veille.normalize.text import content_hash

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResanitizeReport:
    scanned: int = 0
    #: slug du flux -> nombre d'articles dont summary_clean ou le hash change.
    changed: Counter[str] = field(default_factory=Counter)
    applied: bool = False

    @property
    def n_changed(self) -> int:
        return sum(self.changed.values())


def resanitize_articles(session: Session, *, apply: bool) -> ResanitizeReport:
    """Compare chaque article a ce que produirait la normalisation actuelle.

    Sans `apply`, ne fait que compter. Prend le verrou d'ingestion : une
    ingestion concurrente pourrait reviser un article entre notre lecture et
    notre ecriture, qui l'ecraserait avec un resume perime.
    Leve IngestLockedError si une ingestion tourne.
    """
    report = ResanitizeReport(applied=apply)

    with advisory_lock(session) as acquired:
        if not acquired:
            raise IngestLockedError("une ingestion est en cours, reessayer apres")

        rows = session.execute(
            select(
                Article.id,
                Article.title,
                Article.raw_summary,
                Article.summary_clean,
                Article.content_hash,
                Feed.slug,
            ).join(Feed, Article.first_feed_id == Feed.id)
        )

        changes: list[dict[str, object]] = []
        for article_id, title, raw_summary, old_clean, old_hash, slug in rows:
            report.scanned += 1
            new_clean = sanitize(raw_summary)
            new_hash = content_hash(title, strip_tags(new_clean))
            if new_clean == old_clean and new_hash == old_hash:
                continue
            report.changed[slug] += 1
            changes.append({"id": article_id, "summary_clean": new_clean, "content_hash": new_hash})

        if apply and changes:
            # UPDATE groupe par cle primaire : aucune autre colonne n'est ecrite.
            session.execute(update(Article), changes)
            # Commit SOUS verrou : relache avant, une ingestion pourrait lire
            # l'ancien hash entre la liberation et notre commit.
            session.commit()

    logger.info(
        "resanitize : %s articles lus, %s a corriger%s",
        report.scanned,
        report.n_changed,
        "" if apply else " (simulation)",
    )
    return report
