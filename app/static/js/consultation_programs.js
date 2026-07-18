(() => {
  "use strict";
  const picker = document.querySelector("[data-program-picker]");
  if (!picker) return;
  const search = picker.querySelector("[data-program-search]");
  const count = picker.querySelector("[data-selection-count]");
  const programInputs = [...picker.querySelectorAll('input[name="program_ids"]')];
  const normalize = (value) => value.toLocaleLowerCase("ko-KR").trim();

  const updateCount = () => {
    count.textContent = `${programInputs.filter((input) => input.checked).length}개 선택`;
    picker.querySelectorAll("[data-program-group]").forEach((group) => {
      const inputs = [...group.querySelectorAll('input[name="program_ids"]')];
      const toggle = group.querySelector("[data-institution-toggle]");
      toggle.checked = inputs.length > 0 && inputs.every((input) => input.checked);
      toggle.indeterminate = inputs.some((input) => input.checked) && !toggle.checked;
    });
  };

  const filter = () => {
    const query = normalize(search.value);
    picker.querySelectorAll("[data-program-option]").forEach((option) => {
      option.hidden = Boolean(query) && !normalize(option.dataset.searchText).includes(query);
    });
    picker.querySelectorAll("[data-program-group]").forEach((group) => {
      group.hidden = [...group.querySelectorAll("[data-program-option]")].every(
        (option) => option.hidden,
      );
    });
  };

  picker.querySelectorAll("[data-institution-toggle]").forEach((toggle) => {
    toggle.addEventListener("change", () => {
      toggle.closest("[data-program-group]").querySelectorAll('input[name="program_ids"]')
        .forEach((input) => { input.checked = toggle.checked; });
      updateCount();
    });
  });
  picker.querySelector("[data-select-visible]").addEventListener("click", () => {
    picker.querySelectorAll("[data-program-option]:not([hidden]) input[name='program_ids']")
      .forEach((input) => { input.checked = true; });
    updateCount();
  });
  programInputs.forEach((input) => input.addEventListener("change", updateCount));
  search.addEventListener("input", filter);
  updateCount();
})();
