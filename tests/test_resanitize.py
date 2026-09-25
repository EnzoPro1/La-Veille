"""Recalcul de summary_clean et du hash sur les articles deja stockes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from conftest import NOW, make_feed, read_fixture
from veille.db import SessionLocal
from veille.errors import IngestLockedError
from veille.ingest.lock import advisory_lock
from veille.ingest.parse import parse_feed
from veille.ingest.store import store_entries
from veille.models import Article
from veille.normalize.html import strip_tags
from veille.normalize.text import content_hash
from veille.resanitize import resanitize_articles

pytestmark = pytest.mark.db

ESCAPED_URL = "https://exemple-echappe.test/actualites/jetbrains-air"
PLAIN_URL = "https://exemple-echappe.test/actualites/texte-brut"
#: Ce que l'ancienne sanitisation stockait : le HTML echappe, garde en entites.
STALE_CLEAN = "&lt;p&gt;Jetbrains tente de prendre de la hauteur.&lt;/p&gt;"


def ingest_fixture(session: Session, when=NOW) -> None:
    feed = make_feed(session, "lemagit")
    parsed = parse_feed(read_fixture("escaped_body.xml"), fetched_at=when)
    store_entries(session, feed_id=feed.id, entries=parsed.entries, now=when)
    session.commit()


def article(session: Session, url: str) -> Article:
    session.expire_all()
    found = session.scalar(select(Article).where(Article.url_canonical == url))
    assert found is not None
    return found


def break_like_the_old_pipeline(session: Session) -> None:
    """Remet l'article dans l'etat ecrit avant le correctif."""
    stale = article(session, ESCAPED_URL)
    stale.summary_clean = STALE_CLEAN
    stale.content_hash = content_hash(stale.title, strip_tags(STALE_CLEAN))
    session.commit()


def test_dry_run_counts_without_writing(session: Session) -> None:
    ingest_fixture(session)
    break_like_the_old_pipeline(session)

    report = resanitize_articles(session, apply=False)

    assert report.scanned == 2
    assert report.changed == {"lemagit": 1}
    assert article(session, ESCAPED_URL).summary_clean == STALE_CLEAN


def test_apply_fixes_summary_and_hash_but_not_the_dates(session: Session) -> None:
    ingest_fixture(session)
    break_like_the_old_pipeline(session)
    before = article(session, ESCAPED_URL)
    dates = (before.updated_at, before.first_seen_at, before.last_seen_at, before.published_at)
    plain_before = article(session, PLAIN_URL).summary_clean

    report = resanitize_articles(session, apply=True)

    assert report.n_changed == 1
    fixed = article(session, ESCAPED_URL)
    assert fixed.summary_clean is not None
    assert fixed.summary_clean.startswith("<p>")
    assert "&lt;" not in fixed.summary_clean
    assert "script" not in fixed.summary_clean.lower()
    assert fixed.content_hash == content_hash(fixed.title, strip_tags(fixed.summary_clean))
    assert (fixed.updated_at, fixed.first_seen_at, fixed.last_seen_at, fixed.published_at) == dates
    assert article(session, PLAIN_URL).summary_clean == plain_before


def test_apply_is_idempotent(session: Session) -> None:
    ingest_fixture(session)
    break_like_the_old_pipeline(session)

    assert resanitize_articles(session, apply=True).n_changed == 1
    assert resanitize_articles(session, apply=True).n_changed == 0


def test_next_ingestion_does_not_mistake_the_fix_for_a_revision(session: Session) -> None:
    """Le hash recalcule est celui que produit l'ingestion : repasser le flux
    apres la reparation ne doit pas dater une revision qui n'a pas eu lieu."""
    ingest_fixture(session)
    break_like_the_old_pipeline(session)
    resanitize_articles(session, apply=True)
    updated_at = article(session, ESCAPED_URL).updated_at

    later = NOW + timedelta(hours=6)
    parsed = parse_feed(read_fixture("escaped_body.xml"), fetched_at=later)
    feed_id = article(session, ESCAPED_URL).first_feed_id
    store_entries(session, feed_id=feed_id, entries=parsed.entries, now=later)
    session.commit()

    assert article(session, ESCAPED_URL).updated_at == updated_at


def test_refuses_to_run_during_an_ingestion(session: Session) -> None:
    ingest_fixture(session)
    break_like_the_old_pipeline(session)

    other = SessionLocal()
    try:
        with advisory_lock(other.get_bind()) as held:
            assert held
            with pytest.raises(IngestLockedError):
                resanitize_articles(session, apply=True)
    finally:
        other.close()

    assert article(session, ESCAPED_URL).summary_clean == STALE_CLEAN
