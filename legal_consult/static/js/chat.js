document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  if (!form) return;

  const messagesBox = document.getElementById("chat-messages");
  const textarea = form.querySelector("textarea");
  const submitButton = form.querySelector("button[type='submit']");
  const defaultSubmitText = submitButton.textContent;

  const appendBubble = (role, content, time, isError = false, extraClass = "") => {
    messagesBox.querySelector(".chat-placeholder")?.remove();
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

  const renderSources = (article, sources = []) => {
    article.querySelector(".chat-sources")?.remove();
    if (!sources.length) return;

    const wrapper = document.createElement("div");
    wrapper.className = "chat-sources";
    const title = document.createElement("div");
    title.className = "chat-sources-title";
    title.textContent = "Найденные источники";
    wrapper.appendChild(title);

    const list = document.createElement("ol");
    sources.forEach((source) => {
      const item = document.createElement("li");
      const documentTitle = source.document_title || "Нормативный документ";
      const article = source.article_number ? `, статья ${source.article_number}` : "";
      const heading = source.heading ? ` — ${source.heading}` : "";
      item.textContent = `${documentTitle}${article}${heading}`;
      const previewText = source.preview || source.text || "";
      if (previewText.trim()) {
        const preview = document.createElement("div");
        preview.className = "chat-source-preview";
        preview.textContent = `Фрагмент: ${previewText}`;
        item.appendChild(preview);
      }
      list.appendChild(item);
    });
    wrapper.appendChild(list);
    article.appendChild(wrapper);
  };

  const updateBubble = (article, content, time, isError = false, sources = []) => {
    article.classList.remove("loading", "typing", "error");
    if (isError) {
      article.classList.add("error");
    }
    article.querySelector(".chat-text").textContent = content;
    article.querySelector(".chat-time").textContent = time;
    renderSources(article, sources);
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
        data.assistant_message.sources || [],
      );
    } catch (error) {
      updateBubble(loadingBubble, `Ошибка: ${error.message}`, time, true);
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = defaultSubmitText;
    }
  });
});
