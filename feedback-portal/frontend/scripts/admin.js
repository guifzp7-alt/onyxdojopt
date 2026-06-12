const loginPanel = document.querySelector("[data-login-panel]");
const adminPanel = document.querySelector("[data-admin-panel]");
const loginForm = document.querySelector("[data-login-form]");
const loginMessage = document.querySelector("[data-login-message]");
const list = document.querySelector("[data-admin-list]");
const filter = document.querySelector("[data-status-filter]");
const template = document.querySelector("[data-admin-card-template]");
const logoutButton = document.querySelector("[data-logout]");

const formatDate = (value) =>
  new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "Operacao nao concluida.");
  }
  return payload;
}

function showAdmin() {
  loginPanel.classList.add("hidden");
  adminPanel.classList.remove("hidden");
}

function showLogin() {
  adminPanel.classList.add("hidden");
  loginPanel.classList.remove("hidden");
}

async function loadFeedbacks() {
  try {
    const status = filter.value === "Todos" ? "" : `?status=${encodeURIComponent(filter.value)}`;
    const payload = await request(`/api/admin/feedbacks${status}`);
    showAdmin();
    render(payload.feedbacks);
  } catch {
    showLogin();
  }
}

function render(feedbacks) {
  list.innerHTML = "";
  if (!feedbacks.length) {
    list.innerHTML = '<article class="admin-card"><p>Nenhum feedback encontrado para este filtro.</p></article>';
    return;
  }

  feedbacks.forEach((feedback) => {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.id = feedback.id;
    node.querySelector("[data-name]").textContent = feedback.name;
    node.querySelector("[data-meta]").textContent = `${feedback.user_type} | ${formatDate(feedback.submitted_at)} | Nota ${feedback.rating}`;
    node.querySelector("[data-status]").textContent = feedback.status;

    node.querySelector('[data-edit="name"]').value = feedback.name;
    node.querySelector('[data-edit="user_type"]').value = feedback.user_type;
    node.querySelector('[data-edit="team_time"]').value = feedback.team_time || "";
    node.querySelector('[data-edit="rating"]').value = feedback.rating;
    node.querySelector('[data-edit="comment"]').value = feedback.comment;
    node.querySelector('[data-edit="publish_authorized"]').checked = feedback.publish_authorized;

    node.addEventListener("click", (event) => handleAction(event, node));
    list.append(node);
  });
}

async function handleAction(event, node) {
  const button = event.target.closest("[data-action]");
  if (!button) return;

  const id = node.dataset.id;
  const action = button.dataset.action;

  if (action === "delete") {
    if (!confirm("Excluir este feedback?")) return;
    await request(`/api/admin/feedbacks/${id}`, { method: "DELETE" });
    return loadFeedbacks();
  }

  const data = {
    name: node.querySelector('[data-edit="name"]').value,
    user_type: node.querySelector('[data-edit="user_type"]').value,
    team_time: node.querySelector('[data-edit="team_time"]').value,
    rating: Number(node.querySelector('[data-edit="rating"]').value),
    comment: node.querySelector('[data-edit="comment"]').value,
    publish_authorized: node.querySelector('[data-edit="publish_authorized"]').checked,
  };

  if (action === "approve") data.status = "Aprovado";
  if (action === "reject") data.status = "Rejeitado";

  await request(`/api/admin/feedbacks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  loadFeedbacks();
}

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.textContent = "";
  const data = Object.fromEntries(new FormData(loginForm).entries());
  try {
    await request("/api/admin/login", { method: "POST", body: JSON.stringify(data) });
    loginForm.reset();
    loadFeedbacks();
  } catch (error) {
    loginMessage.textContent = error.message;
  }
});

filter?.addEventListener("change", loadFeedbacks);

logoutButton?.addEventListener("click", async () => {
  await request("/api/admin/logout", { method: "POST", body: "{}" });
  showLogin();
});

loadFeedbacks();
