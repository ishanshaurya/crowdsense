"use strict";
// Web chat page. Every text goes on screen through textContent, never innerHTML: the edit
// menu echoes saved answers (an email, a typed place), so HTML would be an XSS hole.
(() => {
  const log = document.getElementById("log");
  const buttons = document.getElementById("buttons");
  const form = document.getElementById("compose");
  const input = document.getElementById("text");
  const randomId = () =>
    Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
  const user = randomId(); // a new fan on every page load (#83)
  let current = null; // the last reply that had buttons
  let busy = false;

  function bubble(text, who) {
    const p = document.createElement("p");
    p.className = "bubble " + who;
    p.textContent = text;
    log.appendChild(p);
    p.scrollIntoView({ block: "end" });
  }

  function showButtons(reply) {
    buttons.replaceChildren();
    if (!reply) return;
    for (const option of reply.options) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = option.label;
      button.addEventListener("click", () => tap(reply, option));
      buttons.appendChild(button);
    }
  }

  async function post(body) {
    const request = {
      method: "POST",
      headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" },
      body: JSON.stringify(body),
    };
    try {
      return await fetch("/chat/message", request);
    } catch {
      return await fetch("/chat/message", request); // same msg_id: the server dedupes it
    }
  }

  async function send(fields) {
    if (busy) return;
    busy = true;
    buttons.replaceChildren();
    try {
      const response = await post({ user, msg_id: randomId(), ...fields });
      const data = await response.json().catch(() => ({}));
      if (response.status === 429) {
        bubble("Too many messages. Wait a few seconds and try again.", "system");
      } else if (!response.ok) {
        bubble(data.error || "Something went wrong, please try again.", "system");
      } else {
        current = null;
        for (const reply of data.replies) {
          bubble(reply.text, "bot");
          current = reply.options.length ? reply : null;
        }
      }
    } catch {
      bubble("Network problem. Please try again.", "system");
    } finally {
      showButtons(current);
      busy = false;
    }
  }

  function tap(reply, option) {
    if (busy) return;
    bubble("✓ " + option.label, "fan");
    send({ kind: "choice", choice_step: reply.step_id, choice_id: option.id });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    bubble(text, "fan");
    send({ kind: "text", text });
  });

  const src = new URLSearchParams(location.search).get("src");
  send(src ? { kind: "start", src } : { kind: "start" });
})();
