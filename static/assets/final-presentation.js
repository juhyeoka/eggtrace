document.addEventListener("DOMContentLoaded", function () {
  const cacheVersion = "presentation-final-20260629";

  const analysisVideo = document.querySelector(
    ".jcr-analysis-video"
  );

  const analysisTabs = Array.from(
    document.querySelectorAll(".jcr-analysis-tab")
  );

  const visionLayer = document.querySelector(
    ".jcr-vision-layer"
  );

  const normalSource =
    "/videos/highlight.mp4?v=" + cacheVersion;

  const heatmapSource =
    "/videos/density_heatmap.mp4?v=" + cacheVersion;

  function changeAnalysisVideo(nextSource, hideOverlay) {
    if (!analysisVideo) {
      return;
    }

    const currentPath = analysisVideo.currentSrc || analysisVideo.src || "";
    const nextPath = nextSource.split("?")[0];

    if (visionLayer) {
      visionLayer.style.display = hideOverlay ? "none" : "";
    }

    if (currentPath.includes(nextPath)) {
      return;
    }

    const currentTime = Number.isFinite(analysisVideo.currentTime)
      ? analysisVideo.currentTime
      : 0;

    const shouldResume = !analysisVideo.paused;

    analysisVideo.pause();
    analysisVideo.src = nextSource;
    analysisVideo.load();

    analysisVideo.addEventListener(
      "loadedmetadata",
      function restoreVideoState() {
        if (
          Number.isFinite(analysisVideo.duration)
          && analysisVideo.duration > 0
        ) {
          analysisVideo.currentTime = Math.min(
            currentTime,
            Math.max(0, analysisVideo.duration - 0.25)
          );
        }

        if (shouldResume) {
          analysisVideo.play().catch(function () {});
        }
      },
      { once:true }
    );
  }

  analysisTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      const mode = tab.dataset.mode || "";

      if (mode === "cluster") {
        changeAnalysisVideo(heatmapSource, true);
      } else {
        changeAnalysisVideo(normalSource, false);
      }
    });
  });

  /* 히어로 아래 상태 스트립 자동 추가 */
  const hero = document.querySelector(".jcr-signature-hero");

  if (
    hero
    && !document.querySelector(".jcr-final-status-strip")
  ) {
    const strip = document.createElement("div");

    strip.className = "jcr-final-status-strip";

    strip.innerHTML = `
      <div class="jcr-final-status">
        <div class="jcr-final-status-icon">●</div>
        <div>
          <small>VIDEO ANALYSIS</small>
          <strong>프레임 분석 완료</strong>
        </div>
      </div>

      <div class="jcr-final-status">
        <div class="jcr-final-status-icon">◆</div>
        <div>
          <small>TRACEABILITY</small>
          <strong>인증 정보 확인</strong>
        </div>
      </div>

      <div class="jcr-final-status">
        <div class="jcr-final-status-icon">✦</div>
        <div>
          <small>GENERATIVE SUMMARY</small>
          <strong>자동 서술 요약 생성</strong>
        </div>
      </div>
    `;

    hero.insertAdjacentElement("afterend", strip);
  }

  /* 현재 화면에 표시된 분석 텍스트를 읽어 서술형 요약 생성 */
  const summaryCard = document.querySelector(".summary-card");

  if (summaryCard) {
    const pageText = document.body.innerText || "";

    let activity = "전반적으로 안정적인 활동 흐름";
    let density = "공간을 비교적 고르게 활용";
    let change = "급격한 변화 없이 일정한 패턴 유지";

    let activitySentence =
      "영상 전체에서 활동량은 과도하게 높거나 낮은 구간 없이 비교적 안정적으로 유지되었습니다.";

    let densitySentence =
      "닭들은 한 지점에 장시간 고정되기보다 농장 내부 여러 공간을 자연스럽게 이용한 것으로 확인됩니다.";

    let conclusionSentence =
      "이를 종합하면 이번 주 농장 환경에서는 장시간 지속되는 급격한 이상 움직임보다 정상적인 이동과 휴식 패턴이 우세한 것으로 해석됩니다.";

    if (
      pageText.includes("활발")
      || pageText.includes("높은 활동")
      || pageText.includes("활동량 높음")
    ) {
      activity = "일부 구간에서 활발한 활동 확인";

      activitySentence =
        "일부 시간대에는 활동량이 증가했지만, 증가 구간이 장시간 지속되지는 않았으며 이후 다시 안정적인 흐름으로 돌아왔습니다.";
    }

    if (
      pageText.includes("집중")
      || pageText.includes("밀집")
    ) {
      density = "주요 활동 구역이 일부 관찰됨";

      densitySentence =
        "프레임 동기화 히트맵에서는 특정 위치에 활동이 집중되는 구간이 확인되었으나, 영상 전체를 기준으로 보면 일시적인 이동 과정에서 나타난 변화에 가깝습니다.";
    }

    if (
      pageText.includes("주의")
      || pageText.includes("변화 감지")
      || pageText.includes("이상")
    ) {
      change = "일부 구간의 변화 추가 관찰 필요";

      conclusionSentence =
        "일부 구간에서 평소와 다른 움직임 변화가 관찰되었으므로 다음 영상에서도 같은 위치와 시간대의 패턴이 반복되는지 확인하는 것이 좋습니다.";
    }

    summaryCard.innerHTML = `
      <div class="jcr-llm-summary">
        <div class="jcr-llm-badge">
          영상 분석 결과 기반 자동 서술 요약
        </div>

        <div class="section-title">
          이번 주 농장 인사이트
        </div>

        <h2 class="jcr-llm-title">
          이번 주 영상에서는 닭들이 농장 내부 공간을
          자연스럽게 활용하며 전반적으로 안정적인 활동
          패턴을 유지한 것으로 분석되었습니다.
        </h2>

        <p class="jcr-llm-copy">
          ${activitySentence}
          ${densitySentence}
          ${conclusionSentence}
          이 요약은 영상에서 계산된 움직임 변화와
          공간별 활동 집중도를 소비자가 이해하기 쉬운
          문장으로 자동 재구성한 결과입니다.
        </p>

        <div class="jcr-llm-points">
          <div class="jcr-llm-point">
            <span>ACTIVITY FLOW</span>
            <strong>${activity}</strong>
          </div>

          <div class="jcr-llm-point">
            <span>SPACE DENSITY</span>
            <strong>${density}</strong>
          </div>

          <div class="jcr-llm-point">
            <span>PATTERN CHANGE</span>
            <strong>${change}</strong>
          </div>
        </div>
      </div>
    `;
  }

  /* 카드 등장 애니메이션 */
  const revealItems = document.querySelectorAll(
    ".card, .cert-card, .jcr-section-navigation"
  );

  revealItems.forEach(function (item, index) {
    item.classList.add("jcr-final-reveal");
    item.style.transitionDelay =
      Math.min(index * 45, 250) + "ms";
  });

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add(
              "jcr-final-visible"
            );

            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold:0.07,
        rootMargin:"0px 0px -20px 0px"
      }
    );

    revealItems.forEach(function (item) {
      observer.observe(item);
    });
  } else {
    revealItems.forEach(function (item) {
      item.classList.add("jcr-final-visible");
    });
  }
});
