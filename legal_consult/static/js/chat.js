document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  if (!form) return;

  const messagesBox = document.getElementById("chat-messages");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector("button[type='submit']");
  const defaultSubmitText = submitButton.textContent;

  const appendBubble = (role, content, time, isError = false, extraClass = "") => {
    const article = document.createElement("article");
    article.className = `chat-bubble ${role}${isError ? " error" : ""}${extraClass ? ` ${extraClass}` : ""}`;
    article.innerHTML = `
      <div class="chat-role">${role === "user" ? "Пользователь" : "Ассистент"}</div>
      <div class="chat-text"></div>
      <div class="chat-time">${time}</div>
    `;
    article.querySelector(".chat-text").textContent = content;
    messagesBox.appendChild(article);
    messagesBox.scrollTop = messagesBox.scrollHeight;
    return article;
  };

  const updateBubble = (article, content, time, isError = false) => {
    article.classList.remove("loading", "typing", "error");
    if (isError) {
      article.classList.add("error");
    }
    article.querySelector(".chat-text").textContent = content;
    article.querySelector(".chat-time").textContent = time;
    messagesBox.scrollTop = messagesBox.scrollHeight;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const content = textarea.value.trim();
    if (!content) return;

    const formData = new FormData(form);   // сначала собираем данные

    const now = new Date();
    const time = now.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

    appendBubble("user", content, time);
    const loadingBubble = appendBubble(
      "assistant",
      "Ассистент формирует ответ...",
      time,
      false,
      "loading typing",
    );
    textarea.value = "";
    submitButton.disabled = true;
    submitButton.textContent = "Отправка...";

    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        const fieldError = data?.errors?.content?.[0];
        throw new Error(fieldError || data.detail || "Ошибка обработки сообщения");
      }

      updateBubble(
        loadingBubble,
        data.assistant_message.content,
        data.assistant_message.created_at,
        data.assistant_message.is_error,
      );
    } catch (error) {
      updateBubble(loadingBubble, `Ошибка: ${error.message}`, time, true);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = defaultSubmitText;
    }
  });
});
