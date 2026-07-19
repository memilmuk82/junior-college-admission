(() => {
  const button = document.querySelector('[data-add-score-row]');
  const wrap = document.querySelector('.public-grade-grid-wrap');
  const firstRow = document.querySelector('[data-score-row]');
  if (!button || !wrap || !firstRow) return;
  button.addEventListener('click', () => {
    const rows = wrap.querySelectorAll('[data-score-row]');
    if (rows.length >= 40) return;
    const clone = firstRow.cloneNode(true);
    const index = rows.length;
    clone.querySelectorAll('input').forEach((input) => {
      input.name = input.name.replace(/rows-\d+-/, `rows-${index}-`);
      input.value = '';
    });
    clone.querySelectorAll('select').forEach((select) => {
      select.name = select.name.replace(/rows-\d+-/, `rows-${index}-`);
      select.selectedIndex = 0;
    });
    wrap.appendChild(clone);
    clone.querySelector('input')?.focus();
  });
  wrap.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.matches('[data-delete-score-row]')) return;
    const row = target.closest('[data-score-row]');
    if (!row) return;
    row.querySelectorAll('input').forEach((input) => { input.value = ''; });
    row.hidden = true;
  });
})();

(() => {
  "use strict";
  const alternative = document.querySelector(".alternative-input");
  document.querySelectorAll('input[name="input_mode"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (alternative && input.checked && input.value !== "manual") alternative.open = true;
    });
  });
  const search = document.querySelector("[data-preview-search]");
  const programs = [...document.querySelectorAll("[data-preview-program]")];
  if (!search || !programs.length) return;
  search.addEventListener("input", () => {
    const query = search.value.toLocaleLowerCase("ko-KR").trim();
    programs.forEach((program) => {
      program.hidden = Boolean(query)
        && !program.dataset.searchText.toLocaleLowerCase("ko-KR").includes(query);
    });
  });
})();
