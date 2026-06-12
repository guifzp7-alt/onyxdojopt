const list = document.querySelector("[data-feedback-list]");
const average = document.querySelector("[data-average]");
const total = document.querySelector("[data-total]");

const stars = (rating) => "★★★★★".slice(0, rating) + "☆☆☆☆☆".slice(0, 5 - rating);

const formatDate = (value) =>
  new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(value));

async function loadFeedbacks() {
  const response = await fetch("/api/public/feedbacks");
  const payload = await response.json();

  average.textContent = payload.average.toFixed(1);
  total.textContent = payload.total;

  if (!payload.feedbacks.length) {
    list.innerHTML = '<article class="feedback-card"><p>Nenhum feedback aprovado publicado ainda.</p></article>';
    return;
  }

  list.innerHTML = payload.feedbacks
    .map(
      (feedback) => `
        <article class="feedback-card">
          <div class="stars-view" aria-label="${feedback.rating} de 5 estrelas">${stars(feedback.rating)}</div>
          <p>${feedback.comment}</p>
          <div>
            <strong>${feedback.name}</strong>
            <span>${feedback.user_type} | ${formatDate(feedback.submitted_at)}</span>
          </div>
        </article>
      `,
    )
    .join("");
}

loadFeedbacks();
