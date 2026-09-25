// Le journal sans fin : a l'approche du bas de page, charge la page suivante
// (le meme HTML que la pagination classique) et la colle a la suite.
// Sans JavaScript, ou si un chargement echoue, le lien "suivant" reste la.
(() => {
  "use strict";

  const journal = document.querySelector("[data-journal]");
  const pagination = document.querySelector("[data-pagination]");
  if (!journal || !pagination || !("IntersectionObserver" in window)) return;

  let loading = false;

  const status = document.createElement("p");
  status.className = "loading";
  status.setAttribute("aria-live", "polite");

  async function loadNext() {
    const next = pagination.querySelector("[data-next]");
    if (!next || loading) return;
    loading = true;
    status.textContent = "Chargement de la suite…";
    pagination.before(status);

    try {
      const response = await fetch(next.href, { headers: { Accept: "text/html" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");

      for (const day of doc.querySelectorAll("[data-journal] > .day")) {
        const last = journal.lastElementChild;
        if (last && last.dataset.day === day.dataset.day) {
          // Le jour continue d'une page a l'autre : on prolonge la rubrique
          // existante, sans lui donner une seconde une.
          const grid = last.querySelector(".day-grid");
          for (const article of day.querySelectorAll(".article")) {
            article.removeAttribute("data-lead");
            grid.append(document.adoptNode(article));
          }
        } else {
          journal.append(document.adoptNode(day));
        }
      }

      const newPagination = doc.querySelector("[data-pagination]");
      if (newPagination) pagination.replaceChildren(...newPagination.childNodes);
      status.remove();
      // Si la suite ne remplit pas l'ecran, la pagination reste visible et
      // l'observateur ne se redeclenche pas seul : re-observer force le test.
      observer.unobserve(pagination);
      observer.observe(pagination);
    } catch (error) {
      status.textContent = "La suite n'a pas pu être chargée : utiliser le lien « suivant ».";
      console.error(error);
      observer.disconnect();
    } finally {
      loading = false;
    }
  }

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadNext();
    },
    { rootMargin: "0px 0px 1200px 0px" },
  );
  observer.observe(pagination);
})();
