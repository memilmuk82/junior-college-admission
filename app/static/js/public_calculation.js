(() => {
  "use strict";

  const scoreForm = document.querySelector(".excel-score-form");
  if (!scoreForm) return;

  document.querySelectorAll('input[name="input_mode"]').forEach((input) => {
    input.addEventListener("change", () => {
      const alternative = document.querySelector(".alternative-input");
      if (alternative && input.checked && input.value !== "manual") alternative.open = true;
    });
  });
})();
