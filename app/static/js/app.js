document.documentElement.classList.add("js-ready");

const rowCheckboxes = Array.from(document.querySelectorAll(".row-checkbox"));
const selectedRowCount = document.querySelector("#selected-row-count");
const selectAllRows = document.querySelector("#select-all-rows");

function updateSelectedRows() {
  if (!selectedRowCount) return;
  const checkedCount = rowCheckboxes.filter((checkbox) => checkbox.checked).length;
  selectedRowCount.textContent = String(checkedCount);
  if (selectAllRows) {
    selectAllRows.checked = checkedCount > 0 && checkedCount === rowCheckboxes.length;
    selectAllRows.indeterminate = checkedCount > 0 && checkedCount < rowCheckboxes.length;
  }
}

rowCheckboxes.forEach((checkbox) => checkbox.addEventListener("change", updateSelectedRows));

if (selectAllRows) {
  selectAllRows.addEventListener("change", () => {
    rowCheckboxes.forEach((checkbox) => {
      checkbox.checked = selectAllRows.checked;
    });
    updateSelectedRows();
  });
}

updateSelectedRows();
