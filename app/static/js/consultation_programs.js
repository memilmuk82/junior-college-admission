(() => {
  "use strict";
  const picker = document.querySelector("[data-program-picker]");
  if (!picker) return;
  const search = picker.querySelector("[data-program-search]");
  const institutionFilter = picker.querySelector("[data-institution-filter]");
  const count = document.querySelector("[data-selection-count]");
  const chips = picker.querySelector("[data-selection-chips]");
  const dockCount = document.querySelector("[data-dock-count]");
  const dockLabels = document.querySelector("[data-dock-labels]");
  const selectionMessage = picker.querySelector("[data-selection-message]");
  const programInputs = [...picker.querySelectorAll('input[name="program_ids"]')];
  const maximumSelection = 5;
  const normalize = (value) => value.toLocaleLowerCase("ko-KR").trim();

  const updateCount = () => {
    const selected = programInputs.filter((input) => input.checked);
    if (count) count.textContent = `${selected.length}개 선택`;
    if (dockCount) dockCount.textContent = `${selected.length}개 학과`;
    if (dockLabels) {
      dockLabels.textContent = selected.length
        ? selected.slice(0, 3).map((input) => input.dataset.label).join(" · ")
        : "선택한 학과가 여기에 표시됩니다.";
    }
    if (chips) {
      chips.replaceChildren();
      selected.forEach((input) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "selection-chip";
        button.textContent = `${input.dataset.label} ×`;
        button.addEventListener("click", () => {
          input.checked = false;
          updateCount();
        });
        chips.appendChild(button);
      });
    }
    picker.querySelectorAll("[data-program-group]").forEach((group) => {
      const inputs = [...group.querySelectorAll('input[name="program_ids"]')];
      const toggle = group.querySelector("[data-institution-toggle]");
      toggle.checked = inputs.length > 0 && inputs.every((input) => input.checked);
      toggle.indeterminate = inputs.some((input) => input.checked) && !toggle.checked;
    });
  };

  const filter = () => {
    const query = normalize(search.value);
    const institution = institutionFilter?.value || "";
    picker.querySelectorAll("[data-program-option]").forEach((option) => {
      const queryMismatch = Boolean(query) && !normalize(option.dataset.searchText).includes(query);
      const institutionMismatch = Boolean(institution) && option.dataset.institution !== institution;
      option.hidden = queryMismatch || institutionMismatch;
    });
    picker.querySelectorAll("[data-program-group]").forEach((group) => {
      group.hidden = [...group.querySelectorAll("[data-program-option]")].every(
        (option) => option.hidden,
      );
    });
  };

  picker.querySelectorAll("[data-institution-toggle]").forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const groupInputs = [
        ...toggle.closest("[data-program-group]").querySelectorAll('input[name="program_ids"]'),
      ];
      if (!toggle.checked) {
        groupInputs.forEach((input) => { input.checked = false; });
      } else {
        let available = maximumSelection - programInputs.filter((input) => input.checked).length;
        groupInputs.forEach((input) => {
          if (!input.checked && available > 0) {
            input.checked = true;
            available -= 1;
          }
        });
        if (selectionMessage && groupInputs.some((input) => !input.checked)) {
          selectionMessage.textContent = "한 번에 최대 5개까지 선택할 수 있습니다.";
        }
      }
      updateCount();
    });
  });
  picker.querySelector("[data-select-visible]").addEventListener("click", () => {
    let available = maximumSelection - programInputs.filter((input) => input.checked).length;
    const visibleInputs = [
      ...picker.querySelectorAll("[data-program-option]:not([hidden]) input[name='program_ids']"),
    ];
    visibleInputs.forEach((input) => {
      if (!input.checked && available > 0) {
        input.checked = true;
        available -= 1;
      }
    });
    if (selectionMessage && visibleInputs.some((input) => !input.checked)) {
      selectionMessage.textContent = "한 번에 최대 5개까지 선택할 수 있습니다.";
    }
    updateCount();
  });
  programInputs.forEach((input) => input.addEventListener("change", () => {
    if (input.checked && programInputs.filter((candidate) => candidate.checked).length > maximumSelection) {
      input.checked = false;
      if (selectionMessage) {
        selectionMessage.textContent = "한 번에 최대 5개까지 선택할 수 있습니다.";
      }
    }
    updateCount();
  }));
  search.addEventListener("input", filter);
  institutionFilter?.addEventListener("change", filter);
  updateCount();
})();
