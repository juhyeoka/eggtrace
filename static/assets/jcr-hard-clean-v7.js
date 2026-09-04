(function () {
  "use strict";

  function normalize(value) {
    return String(value || "")
      .replace(/\s+/g, "")
      .replace(/[·|｜]/g, "");
  }

  function isOldThreeStepBar(element) {
    if (!element || !(element instanceof HTMLElement)) {
      return false;
    }

    if (
      element.id === "jcr-final-toc" ||
      element.closest("#jcr-final-toc")
    ) {
      return false;
    }

    if (
      element.querySelector(
        "video, iframe, table, form, input, textarea"
      )
    ) {
      return false;
    }

    const text = normalize(element.textContent);

    const hasStep1 =
      text.includes("01농장영상");

    const hasStep2 =
      text.includes("02인공지능분석") ||
      text.includes("02영상분석");

    const hasStep3 =
      text.includes("03공식인증") ||
      text.includes("03인증정보");

    const isNewFourStepMenu =
      text.includes("04공식인증") ||
      text.includes("이번주요약") ||
      text.includes("닭생활상태");

    if (
      !hasStep1 ||
      !hasStep2 ||
      !hasStep3 ||
      isNewFourStepMenu
    ) {
      return false;
    }

    const rect = element.getBoundingClientRect();

    return (
      rect.width > 250 &&
      rect.height > 20 &&
      rect.height < 220
    );
  }

  function removeOldBars() {
    document
      .querySelectorAll(
        ".jcr-process, .jcr-old-process, .jcr-step-strip"
      )
      .forEach((element) => element.remove());

    const candidates = Array.from(
      document.querySelectorAll(
        "nav, section, article, div, ul"
      )
    );

    const matches = candidates
      .filter(isOldThreeStepBar)
      .sort((a, b) => {
        const aChildren =
          a.querySelectorAll("*").length;

        const bChildren =
          b.querySelectorAll("*").length;

        return aChildren - bChildren;
      });

    matches.forEach((element) => {
      if (
        document.body.contains(element) &&
        isOldThreeStepBar(element)
      ) {
        element.remove();
      }
    });
  }

  function finalizeI4Page() {
    const page = document.querySelector(".page");
    const topbar = page?.querySelector(".topbar");
    const video = page?.querySelector(
      ".main-video-section"
    );

    if (!page || !video) {
      return;
    }

    if (topbar && !topbar.querySelector(".jcr-main-logo")) {
      const brand = document.createElement("div");
      const logo = document.createElement("img");

      brand.className = "brand";
      logo.className = "jcr-main-logo";
      logo.src = "/assets/logo.png?v=i4-company-20260825";
      logo.alt = "i4 COMPANY";
      brand.appendChild(logo);
      topbar.replaceChildren(brand);
    }

    [
      "#jcr-premium-hero",
      "#jcr-final-toc",
      "#jcr-final-top-brand",
      ".jcr-signature-hero",
      ".jcr-section-navigation"
    ].forEach((selector) => {
      page.querySelectorAll(selector).forEach(
        (element) => element.remove()
      );
    });

    const certifications = document.getElementById(
      "certifications"
    );
    const report = document.getElementById(
      "eggtrace-patent-ui"
    );

    if (topbar && page.firstElementChild !== topbar) {
      page.prepend(topbar);
    }

    if (
      topbar &&
      video.previousElementSibling !== topbar
    ) {
      topbar.insertAdjacentElement(
        "afterend",
        video
      );
    } else if (
      !topbar &&
      page.firstElementChild !== video
    ) {
      page.prepend(video);
    }

    if (
      certifications &&
      video.nextElementSibling !== certifications
    ) {
      video.insertAdjacentElement(
        "afterend",
        certifications
      );
    }

    if (
      report &&
      certifications &&
      certifications.nextElementSibling !== report
    ) {
      certifications.insertAdjacentElement(
        "afterend",
        report
      );
    }

    document.title =
      "i4 COMPANY | 농장 투명성 리포트";
  }

  function clean() {
    removeOldBars();
    finalizeI4Page();
  }

  function start() {
    clean();

    [100, 400, 900, 1600, 2600].forEach(
      (delay) => {
        window.setTimeout(clean, delay);
      }
    );

    const observer = new MutationObserver(() => {
      clean();
    });

    observer.observe(document.body, {
      childList:true,
      subtree:true
    });

    window.setTimeout(() => {
      observer.disconnect();
      clean();
    }, 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start
    );
  } else {
    start();
  }
})();
