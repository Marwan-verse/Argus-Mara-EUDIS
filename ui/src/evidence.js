import { mount } from "svelte";
import ReviewForm from "./ReviewForm.svelte";
import PrintButton from "./PrintButton.svelte";
// Keep Python-rendered evidence readable without JS and self-contained on file://.
for (const form of document.querySelectorAll("form[data-review]")) {
  const target = document.createElement("div");
  form.replaceWith(target);
  mount(ReviewForm, { target });
}
for (const button of document.querySelectorAll("[data-print]")) {
  const target = document.createElement("span");
  button.replaceWith(target);
  mount(PrintButton, { target });
}
