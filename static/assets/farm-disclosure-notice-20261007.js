(() => {
  const notice = document.querySelector("#eggtraceFarmNotice");
  if (!notice) return;
  if (window.location.pathname.replace(/\/$/, "") !== "/p/EGG-0001") return;

  const storageKey = "eggtrace:farm-disclosure-notice:2026-10-07:hidden-until";
  const hiddenDuration = 24 * 60 * 60 * 1000;

  try {
    const hiddenUntil = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(hiddenUntil) && hiddenUntil > Date.now()) return;
    localStorage.removeItem(storageKey);
  } catch {
    // 저장소를 사용할 수 없는 환경에서도 안내와 닫기는 동작합니다.
  }

  notice.querySelector("[data-eggtrace-notice-close]").addEventListener("click", () => {
    notice.close();
  });

  notice.querySelector("[data-eggtrace-notice-hide]").addEventListener("click", () => {
    try {
      localStorage.setItem(storageKey, String(Date.now() + hiddenDuration));
    } catch {
      // 브라우저가 저장을 제한하면 현재 화면의 안내만 닫습니다.
    }
    notice.close();
  });

  notice.addEventListener("close", () => {
    document.documentElement.classList.remove("eggtrace-farm-notice-open");
  });

  notice.addEventListener("click", (event) => {
    if (event.target !== notice) return;
    const bounds = notice.getBoundingClientRect();
    if (
      event.clientX < bounds.left || event.clientX > bounds.right ||
      event.clientY < bounds.top || event.clientY > bounds.bottom
    ) notice.close();
  });

  notice.showModal();
  document.documentElement.classList.add("eggtrace-farm-notice-open");
})();
