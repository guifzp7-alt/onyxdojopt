const form = document.querySelector("[data-feedback-form]");
const message = document.querySelector("[data-form-message]");

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";

  const data = Object.fromEntries(new FormData(form).entries());
  data.publish_authorized = form.elements.publish_authorized.checked;

  try {
    const response = await fetch("/api/feedbacks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || "Nao foi possivel enviar o feedback.");
    }

    form.reset();
    message.textContent = "Obrigado pelo seu feedback! Sua avaliação foi recebida e será analisada antes da publicação.";
  } catch (error) {
    message.textContent = error.message;
  }
});
