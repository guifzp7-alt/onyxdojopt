const body = document.body;
const toggle = document.querySelector("[data-nav-toggle]");
const nav = document.querySelector("[data-nav]");
if (toggle && nav) {
  toggle.addEventListener("click", () => {
    const isOpen = body.classList.toggle("nav-open");
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Fechar menu" : "Abrir menu");
  });

  nav.addEventListener("click", (event) => {
    if (event.target instanceof HTMLAnchorElement) {
      body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Abrir menu");
    }
  });
}

const feedbackContainer = document.querySelector("[data-approved-feedbacks]");
const feedbackList = document.querySelector("[data-feedback-list]");
const feedbackAverage = document.querySelector("[data-feedback-average]");
const feedbackTotal = document.querySelector("[data-feedback-total]");

const FEEDBACK_API_URL =
  window.location.protocol === "file:" || ["5500", "5501"].includes(window.location.port)
    ? "http://localhost:8000/api/public/feedbacks"
    : "/api/public/feedbacks";

const renderStars = (rating) => "★★★★★".slice(0, rating) + "☆☆☆☆☆".slice(0, 5 - rating);

const formatFeedbackDate = (value) =>
  new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));

const escapeHtml = (value) => {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
};

async function loadApprovedFeedbacks() {
  if (!feedbackContainer || !feedbackList) return;

  try {
    const response = await fetch(FEEDBACK_API_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("Feedbacks indisponíveis.");

    const data = await response.json();
    if (!data.feedbacks?.length) return;

    feedbackAverage.textContent = Number(data.average || 0).toLocaleString("pt-BR", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
    feedbackTotal.textContent = data.total;
    feedbackList.innerHTML = data.feedbacks
      .slice(0, 6)
      .map(
        (feedback) => `
          <article class="approved-feedback-card">
            <div class="feedback-stars" aria-label="${feedback.rating} de 5 estrelas">${renderStars(feedback.rating)}</div>
            <p>${escapeHtml(feedback.comment)}</p>
            <span>${escapeHtml(feedback.name)} | ${escapeHtml(feedback.user_type)} | ${formatFeedbackDate(feedback.submitted_at)}</span>
          </article>
        `,
      )
      .join("");
    feedbackContainer.hidden = false;
  } catch (error) {
    feedbackContainer.hidden = true;
  }
}

loadApprovedFeedbacks();
