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

  const profileInputs = [...document.querySelectorAll('input[name="student_profile"]')];
  const applyProfileLabels = () => {
    const profile = profileInputs.find((input) => input.checked)?.value || "VOCATIONAL_CURRENT";
    const vocationalCurrent = profile === "VOCATIONAL_CURRENT";
    document.querySelectorAll("[data-derived-record-source]").forEach((input) => {
      input.value = vocationalCurrent && input.dataset.grade === "3"
        ? "VOCATIONAL_TRAINING_RECORD"
        : "HOME_SCHOOL_RECORD";
    });
    document.querySelectorAll("[data-derived-vocational-semester]").forEach((input) => {
      input.value = vocationalCurrent && input.dataset.grade === "3" ? "TRUE" : "FALSE";
    });
    document.querySelectorAll("[data-term-source-label]").forEach((label) => {
      label.textContent = vocationalCurrent && label.dataset.grade === "3"
        ? "직업위탁 성적"
        : "원적교 학교생활기록부";
    });
    document.querySelectorAll("[data-row-source-label]").forEach((label) => {
      label.textContent = vocationalCurrent && label.dataset.grade === "3"
        ? "성적 구분: 직업위탁 성적 · 위탁 학기"
        : "성적 구분: 원적교 학교생활기록부 · 일반 학기";
    });
    const help = document.querySelector("[data-profile-source-help]");
    if (help) {
      help.textContent = vocationalCurrent
        ? "1·2학년은 원적교 학교생활기록부, 3학년은 직업위탁 성적으로 서버에서 분류합니다."
        : "일반고 졸업생의 전 학년 성적은 원적교 학교생활기록부로 분류합니다.";
    }
  };
  profileInputs.forEach((input) => input.addEventListener("change", applyProfileLabels));
  applyProfileLabels();
})();
