"use strict";

document.querySelectorAll("[data-print]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});

document.querySelectorAll("[data-review]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const note = form.elements.note.value.trim();
    if (!note) {
      form.querySelector("[data-review-status]").textContent = "Enter a review note.";
      return;
    }
    // Page-local acknowledgement only; no network, persistent storage or response action.
    form.querySelector("[data-review-status]").textContent =
      `Local review recorded at ${new Date().toISOString()}: ${note}. No operational action was authorized.`;
  });
});
