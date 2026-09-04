(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function percent(value, digits = 1) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
      return "-";
    }

    return (number * 100).toFixed(digits) + "%";
  }

  function fixed(value, digits = 2) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
      return "-";
    }

    return number.toFixed(digits);
  }

  function friendlyZoneName(name, index) {
    const table = {
      zone0:"왼쪽 구역",
      zone1:"가운데 왼쪽",
      zone2:"가운데 오른쪽",
      zone3:"오른쪽 구역",
      feed:"먹이 구역",
      water:"물 구역",
      door:"출입구 주변"
    };

    return table[name] || "구역 " + (index + 1);
  }

  function directionText(value) {
    const table = {
      left:"왼쪽 방향",
      right:"오른쪽 방향",
      up:"위쪽 방향",
      down:"아래쪽 방향",
      northeast:"오른쪽 위 방향",
      northwest:"왼쪽 위 방향",
      southeast:"오른쪽 아래 방향",
      southwest:"왼쪽 아래 방향",
      stationary:"뚜렷한 방향 없음",
      "←":"왼쪽 방향",
      "→":"오른쪽 방향",
      "↑":"위쪽 방향",
      "↓":"아래쪽 방향",
      "↗":"오른쪽 위 방향",
      "↖":"왼쪽 위 방향",
      "↘":"오른쪽 아래 방향",
      "↙":"왼쪽 아래 방향"
    };

    return table[String(value || "").toLowerCase()]
      || value
      || "뚜렷한 방향 없음";
  }

  function eventName(name) {
    const table = {
      motion_detected:"움직임이 감지된 기록",
      activity_detected:"활동 변화가 감지된 기록",
      crowding_detected:"한곳에 모인 기록",
      unusual_activity:"평소와 다른 움직임 기록"
    };

    return table[name] || name || "분석 기록";
  }

  function createRoot() {
    const old = document.getElementById(
      "eggtrace-patent-ui"
    );

    if (old) {
      old.remove();
    }

    const root = document.createElement("section");
    root.id = "eggtrace-patent-ui";

    root.innerHTML = `
      <div class="egg-report-shell">
        <div class="egg-report-head">
          <div class="egg-report-badge">
            실제 농장 영상 분석 결과
          </div>

          <h2 class="egg-report-title">
            궁금한 내용을 골라 쉽게 확인해 보세요
          </h2>

          <p class="egg-report-description">
            같은 농장 기록이라도 한눈에 보기,
            닭 생활 상태, 먹거리 안심 정보,
            자세한 분석으로 나누어 보여드립니다.
          </p>

          <div class="egg-mode-tabs">
            <button
              type="button"
              class="egg-mode-button active"
              data-view="simple"
            >
              한눈에 보기
            </button>

            <button
              type="button"
              class="egg-mode-button"
              data-view="welfare"
            >
              닭 생활 상태
            </button>

            <button
              type="button"
              class="egg-mode-button"
              data-view="safety"
            >
              먹거리 안심 정보
            </button>

            <button
              type="button"
              class="egg-mode-button"
              data-view="detail"
            >
              분석 자세히
            </button>
          </div>
        </div>

        <div
          id="egg-report-body"
          class="egg-report-content"
        >
          <div class="egg-loading">
            실제 분석 기록을 불러오고 있습니다.
          </div>
        </div>
      </div>
    `;

    const certifications = document.getElementById(
      "certifications"
    );
    const summary = document.querySelector(
      ".summary-card, .jcr-analysis-card"
    );

    if (certifications && certifications.parentNode) {
      certifications.insertAdjacentElement("afterend", root);
    } else if (summary && summary.parentNode) {
      summary.parentNode.insertBefore(root, summary);
    } else {
      document.body.appendChild(root);
    }

    return root;
  }

  function zoneRows(data) {
    const zones = Array.isArray(data.zones)
      ? data.zones
      : [];

    if (!zones.length) {
      return `
        <div class="egg-data-note">
          구역별 분석 기록은 아직 없습니다.
        </div>
      `;
    }

    const maximum = Math.max(
      ...zones.map((zone) => Number(zone.value) || 0),
      0.000001
    );

    return `
      <div class="egg-zone-list">
        ${zones.map((zone, index) => {
          const value = Number(zone.value) || 0;
          const width = Math.max(
            2,
            Math.min(100, value / maximum * 100)
          );

          return `
            <div class="egg-zone-row">
              <div class="egg-zone-name">
                ${escapeHtml(
                  friendlyZoneName(zone.name, index)
                )}
              </div>

              <div class="egg-zone-track">
                <div
                  class="egg-zone-fill"
                  style="width:${width}%"
                ></div>
              </div>

              <div class="egg-zone-value">
                ${percent(zone.share, 0)}
              </div>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  function eventRows(data) {
    const entries = Object.entries(
      data.event_types || {}
    );

    if (!entries.length) {
      return `
        <div class="egg-data-note">
          종류별 분석 기록은 아직 없습니다.
        </div>
      `;
    }

    return `
      <div class="egg-event-list">
        ${entries.map(([name, count]) => `
          <div class="egg-event-row">
            <span>${escapeHtml(eventName(name))}</span>
            <strong>${Number(count) || 0}건</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function integrityView(data) {
    const integrity = data.integrity || {};

    let iconClass = "pending";
    let icon = "!";
    let title = "기록 확인 준비 중";
    let description =
      "현재 분석 로그에는 이전 기록과 연결된 해시 정보가 충분하지 않아 자동 연결 검증은 아직 진행하지 않았습니다.";

    if (integrity.available && integrity.ok) {
      iconClass = "";
      icon = "✓";
      title = "분석 기록 연결에 이상이 없습니다";
      description =
        "앞 기록의 식별값과 다음 기록의 연결값이 순서대로 일치하는 것을 확인했습니다.";
    }

    if (integrity.available && !integrity.ok) {
      iconClass = "fail";
      icon = "×";
      title = "분석 기록 연결을 다시 확인해야 합니다";
      description =
        "일부 기록의 연결값이 앞 기록과 일치하지 않았습니다.";
    }

    return `
      <div class="egg-integrity-box">
        <div class="egg-integrity-icon ${iconClass}">
          ${icon}
        </div>

        <div>
          <h4>${title}</h4>
          <p>${description}</p>

          ${
            integrity.file_fingerprint
              ? `
                <span class="egg-fingerprint">
                  기록 식별값
                  ${escapeHtml(
                    integrity.file_fingerprint.slice(0, 16)
                  )}
                </span>
              `
              : ""
          }
        </div>
      </div>
    `;
  }

  function renderViews(root, data) {
    const body = root.querySelector(
      "#egg-report-body"
    );

    const overview = data.overview || {};
    const metrics = data.metrics || {};
    const topZone = data.top_zone || {};
    const reliability =
      Number.isFinite(Number(metrics.average_confidence))
        ? percent(metrics.average_confidence, 0)
        : "별도 값 없음";

    body.innerHTML = `
      <section
        class="egg-view"
        data-panel="simple"
      >
        <div class="egg-summary-hero">
          <div class="egg-summary-main">
            <div class="egg-summary-label">
              최근 농장 상태
            </div>

            <div class="egg-summary-sentence">
              ${escapeHtml(
                overview.headline
                || "최근 농장 상태를 분석했습니다."
              )}
            </div>

            <p class="egg-summary-sub">
              ${escapeHtml(
                overview.description
                || "실제 영상 분석 기록을 바탕으로 정리한 결과입니다."
              )}
            </p>
          </div>

          <div class="egg-summary-side">
            <div class="egg-simple-card">
              <small>움직임 상태</small>
              <strong>
                ${escapeHtml(
                  overview.activity_label
                  || "분석 중"
                )}
              </strong>
              <p>
                평균 움직임
                ${percent(metrics.average_motion)}
              </p>
            </div>

            <div class="egg-simple-card">
              <small>공간 이용</small>
              <strong>
                ${escapeHtml(
                  overview.space_label
                  || "분석 중"
                )}
              </strong>
              <p>
                가장 활동이 많았던 곳:
                ${escapeHtml(
                  friendlyZoneName(
                    topZone.name,
                    topZone.index || 0
                  )
                )}
              </p>
            </div>

            <div class="egg-simple-card">
              <small>움직임 변화</small>
              <strong>
                ${escapeHtml(
                  overview.variation_label
                  || "분석 중"
                )}
              </strong>
              <p>
                실제 기록
                ${Number(data.records_analyzed) || 0}건 기준
              </p>
            </div>
          </div>
        </div>

        <div class="egg-data-note">
          임의의 시연값이 아니라
          ${escapeHtml(data.source_name || "분석 기록")}
          에 저장된 실제 값으로 계산했습니다.
          ${
            data.latest_time
              ? `마지막 분석 기록: ${escapeHtml(data.latest_time)}`
              : ""
          }
        </div>
      </section>

      <section
        class="egg-view"
        data-panel="welfare"
        hidden
      >
        <h3 class="egg-view-title">
          닭들이 어떻게 생활했는지 확인해 보세요
        </h3>

        <p class="egg-view-description">
          움직임의 양, 시간에 따른 변화,
          주로 머문 구역과 이동 방향을
          소비자가 이해하기 쉬운 말로 정리했습니다.
        </p>

        <div class="egg-grid-3">
          <article class="egg-info-card green">
            <div class="egg-info-icon">↗</div>
            <h4>평균 움직임</h4>
            <span class="egg-number">
              ${percent(metrics.average_motion)}
            </span>
            <p>
              전체 화면 중 움직임이 확인된
              부분의 평균 비율입니다.
            </p>
          </article>

          <article class="egg-info-card blue">
            <div class="egg-info-icon">⌁</div>
            <h4>움직임 변화 정도</h4>
            <span class="egg-number">
              ${percent(metrics.motion_variability)}
            </span>
            <p>
              시간에 따라 움직임이 얼마나
              크게 달라졌는지 나타냅니다.
            </p>
          </article>

          <article class="egg-info-card gold">
            <div class="egg-info-icon">➜</div>
            <h4>주요 이동 방향</h4>
            <span class="egg-number">
              ${escapeHtml(
                directionText(data.main_direction)
              )}
            </span>
            <p>
              영상에서 가장 자주 나타난
              이동 방향입니다.
            </p>
          </article>
        </div>

        <h3
          class="egg-view-title"
          style="margin-top:25px"
        >
          공간별 활동
        </h3>

        <p class="egg-view-description">
          막대가 길수록 해당 구역에서
          움직임이 더 많이 확인됐습니다.
        </p>

        ${zoneRows(data)}
      </section>

      <section
        class="egg-view"
        data-panel="safety"
        hidden
      >
        <h3 class="egg-view-title">
          정보가 어디에서 왔는지 확인해 보세요
        </h3>

        <p class="egg-view-description">
          영상 분석 기록의 수, 마지막 확인 시각,
          기록 식별값과 연결 상태를 보여드립니다.
          공식 인증 내용은 이 페이지의 인증 카드에서
          함께 확인할 수 있습니다.
        </p>

        <div class="egg-grid-2">
          ${integrityView(data)}

          <div class="egg-integrity-box">
            <div class="egg-integrity-icon">
              i
            </div>

            <div>
              <h4>실제 분석 기록을 사용했습니다</h4>
              <p>
                최근
                ${Number(data.records_analyzed) || 0}건의
                영상 분석 기록을 읽어
                화면의 수치를 계산했습니다.
                분석 신뢰도 평균은
                ${reliability}입니다.
              </p>

              ${
                data.latest_time
                  ? `
                    <span class="egg-fingerprint">
                      마지막 기록
                      ${escapeHtml(data.latest_time)}
                    </span>
                  `
                  : ""
              }
            </div>
          </div>
        </div>

        ${eventRows(data)}
      </section>

      <section
        class="egg-view"
        data-panel="detail"
        hidden
      >
        <h3 class="egg-view-title">
          분석 값을 자세히 확인해 보세요
        </h3>

        <p class="egg-view-description">
          아래 값은 실제 영상 분석 로그에서
          계산된 값입니다. 어려운 영문 용어 대신
          각 숫자가 의미하는 내용을 함께 적었습니다.
        </p>

        <div class="egg-detail-grid">
          <article class="egg-detail-card">
            <small>평균 움직임 비율</small>
            <strong>
              ${percent(metrics.average_motion)}
            </strong>
            <p>
              영상에서 평소 움직임이 확인된 정도
            </p>
          </article>

          <article class="egg-detail-card">
            <small>가장 높았던 움직임 비율</small>
            <strong>
              ${percent(metrics.peak_motion)}
            </strong>
            <p>
              가장 활발했던 순간의 움직임 정도
            </p>
          </article>

          <article class="egg-detail-card">
            <small>움직임 변화 정도</small>
            <strong>
              ${percent(metrics.motion_variability)}
            </strong>
            <p>
              시간별 움직임의 들쭉날쭉한 정도
            </p>
          </article>

          <article class="egg-detail-card">
            <small>평균 이동 강도</small>
            <strong>
              ${fixed(metrics.average_flow)}
            </strong>
            <p>
              프레임 사이에서 이동한 크기의 평균
            </p>
          </article>

          <article class="egg-detail-card">
            <small>한 구역에 모인 정도</small>
            <strong>
              ${percent(metrics.zone_concentration)}
            </strong>
            <p>
              전체 구역 활동 중 가장 큰 구역의 비중
            </p>
          </article>

          <article class="egg-detail-card">
            <small>분석 신뢰도 평균</small>
            <strong>
              ${reliability}
            </strong>
            <p>
              기록에 신뢰도 값이 있을 때만 계산
            </p>
          </article>
        </div>

        ${eventRows(data)}

        <div class="egg-data-note">
          원본 파일:
          ${escapeHtml(data.source_name || "-")}
          · 분석에 사용한 기록:
          ${Number(data.records_analyzed) || 0}건
        </div>
      </section>
    `;

    const buttons = root.querySelectorAll(
      ".egg-mode-button"
    );

    const panels = root.querySelectorAll(
      ".egg-view"
    );

    function changeView(viewName) {
      buttons.forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.view === viewName
        );
      });

      panels.forEach((panel) => {
        panel.hidden =
          panel.dataset.panel !== viewName;
      });

      try {
        localStorage.setItem(
          "eggtrace-consumer-view",
          viewName
        );
      } catch (error) {
        console.debug(error);
      }
    }

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        changeView(button.dataset.view);
      });
    });

    let savedView = "simple";

    try {
      const stored = localStorage.getItem(
        "eggtrace-consumer-view"
      );

      if (
        ["simple", "welfare", "safety", "detail"]
          .includes(stored)
      ) {
        savedView = stored;
      }
    } catch (error) {
      console.debug(error);
    }

    changeView(savedView);
  }

  function renderError(root, message) {
    const body = root.querySelector(
      "#egg-report-body"
    );

    body.innerHTML = `
      <div class="egg-empty">
        ${escapeHtml(message)}
      </div>
    `;
  }

  async function start() {
    const root = createRoot();

    const match = location.pathname.match(
      /\/p\/([^/?#]+)/
    );

    const productCode = match
      ? decodeURIComponent(match[1])
      : "EGG-0001";

    try {
      const response = await fetch(
        "/api/products/"
          + encodeURIComponent(productCode)
          + "/analytics?t="
          + Date.now(),
        {
          cache:"no-store"
        }
      );

      if (!response.ok) {
        throw new Error(
          "서버 응답 " + response.status
        );
      }

      const data = await response.json();

      if (!data.has_data) {
        renderError(
          root,
          "실제 분석 기록을 찾지 못했습니다. "
          + "data/events.jsonl 파일에 기록이 있는지 확인해 주세요."
        );
        return;
      }

      renderViews(root, data);
    } catch (error) {
      console.error(error);

      renderError(
        root,
        "실제 분석값을 불러오지 못했습니다. "
        + "서버 터미널의 오류 내용을 확인해 주세요."
      );
    }
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
