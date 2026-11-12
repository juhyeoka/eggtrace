(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('report-data').textContent);
  const $ = id => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = value; };
  const clock = value => `00:${String(Math.floor(value || 0)).padStart(2, '0')}`;
  const video = $('farm-player');
  const playButton = $('video-play');
  const videoError = $('video-error');
  const sections = [...document.querySelectorAll('[data-section]')];
  const tabs = [...document.querySelectorAll('[data-mode]')];
  const navLinks = [...document.querySelectorAll('.site-header nav a')];
  const modes = {
    farm: { title:'농장 모습', caption:'농장 모습', description:'닭들이 지내는 모습을 그대로 담았어요.', analysis:'움직임이 많았던 때', tag:'영상 전체', detail:'앞뒤 장면을 비교해 움직임을 살펴봤어요. 그래프가 높을수록 움직임이 많이 잡힌 때예요.' },
    activity: { title:'움직임', caption:'움직이는 곳을 찾아보세요', description:'움직임이 잡힌 곳을 초록색으로 표시했어요.', analysis:'지금 장면의 움직임', tag:'현재 장면', detail:'지금 장면의 움직임을 이 영상의 평균과 비교했어요. 1배보다 크면 영상 평균보다 많이 움직인 때예요.' },
    density: { title:'움직인 곳', caption:'움직임이 많았던 곳', description:'움직임이 많은 곳은 노란색이나 붉은색으로 보여요.', analysis:'주로 움직인 곳', tag:'현재 장면', detail:'같은 장면 안에서 움직임을 비교했어요. 색이 진할수록 움직임이 많이 잡힌 곳이에요. 색은 닭의 수를 뜻하지 않아요.' },
    pattern: { title:'이동 방향', caption:'움직인 방향', description:'화살표를 따라 움직인 방향을 볼 수 있어요.', analysis:'시간에 따른 움직임', tag:'시간에 따라', detail:'앞뒤 장면을 비교해 움직인 방향을 표시했어요. 화살표는 방향을, 그래프는 시간에 따라 움직임이 달라진 모습을 보여줘요.' }
  };
  const zoneLabels = {'좌측 상단':'왼쪽 위','상단 중앙':'가운데 위','우측 상단':'오른쪽 위','좌측 중앙':'왼쪽','중앙':'가운데','우측 중앙':'오른쪽','좌측 하단':'왼쪽 아래','하단 중앙':'가운데 아래','우측 하단':'오른쪽 아래'};
  const zoneNames = Object.values(zoneLabels);
  const friendlyZone = name => zoneLabels[name] || name;
  let activeMode = 'farm';
  let analysis = null;
  let graphPoints = [];
  let mediaChange = 0;
  const motionRatio = value => {
    const average = analysis?.summary.averageMotionPercent;
    return average > 0 && Number.isFinite(value) ? (value / average).toFixed(1) : null;
  };

  const certificates = {
    haccp: {
      description: '식품을 만들고 포장하는 동안 안전을 해칠 수 있는 요소를 찾아 관리하는 기준이에요.',
      source: 'https://www.standard.go.kr/KSCI/crtfcSystem/searchCrtfcSystemView.do?crtfcstId=0000000470&crtfcstReformNo=0000&firstChk=ok&menuId=60373&topMenuId=536&upperMenuId=537&viewPage=system'
    },
    antibiotic: {
      description: '사료와 사육 관리가 무항생제축산물 기준에 맞는지 확인하는 인증이에요.',
      source: 'https://www.naqs.go.kr/hp/contents/contentsTab.do?menuId=MN20390'
    },
    sixth: {
      description: '농산물을 생산하면서 가공이나 판매, 체험 사업도 함께 운영하는 곳에 주는 인증이에요.',
      source: 'https://xn--980b99s59h34f6tl.com/home/biz/company.cs?act=view&idx=4504'
    },
    naepo: {
      description: '내포천애는 홍성군에서 함께 사용하는 농특산물 브랜드예요.',
      source: 'https://council.hongseong.go.kr/kr/speakfiveBBSview.do?flag=all&list_style=&page=17&schwrd=&uid=C38E22E0733D88B21D7A1C5CB1346289'
    }
  };

  const dialogs = [...document.querySelectorAll('dialog')];
  const openDialog = dialog => {
    dialogs.forEach(other => { if (other.open) other.close(); });
    video.pause();
    dialog.showModal();
    document.documentElement.classList.add('modal-open');
  };
  dialogs.forEach(dialog => {
    dialog.addEventListener('close', () => {
      if (!dialogs.some(other => other.open)) document.documentElement.classList.remove('modal-open');
    });
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
  });
  document.querySelectorAll('[data-open-purchase]').forEach(button => button.addEventListener('click', () => openDialog($('purchase-dialog'))));
  if (data.purchaseUrl) {
    $('purchase-link').href = data.purchaseUrl;
    $('purchase-link').hidden = false;
    $('purchase-pending').hidden = true;
  }
  document.querySelectorAll('[data-cert]').forEach(button => button.addEventListener('click', () => {
    const certificate = certificates[button.dataset.cert];
    const title = button.dataset.certTitle;
    text('cert-dialog-title', title);
    text('cert-dialog-description', certificate.description);
    const mark = $('cert-dialog-image');
    mark.src = button.dataset.certImage;
    mark.alt = title;

    const sourceLink = $('cert-dialog-source');
    sourceLink.href = certificate.source;
    sourceLink.hidden = false;
    openDialog($('cert-dialog'));
  }));
  $('farm-help').addEventListener('click', () => openDialog($('farm-info')));

  const notice = $('farm-notice');
  const noticeKey = 'eggtrace:farm-notice:20261105:hidden-until';
  let noticeOpened = false;
  const showNotice = () => {
    noticeOpened = true;
    openDialog(notice);
  };
  $('notice-hide').addEventListener('click', () => {
    try { localStorage.setItem(noticeKey, String(Date.now() + 86400000)); } catch { /* Closing is available without storage. */ }
    notice.close();
  });
  $('reopen-notice').addEventListener('click', showNotice);

  // All sections stay in document order; header links are optional shortcuts.
  if ('IntersectionObserver' in window) {
    const sectionObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        navLinks.forEach(link => {
          if (link.hash === '#' + entry.target.id) link.setAttribute('aria-current', 'location');
          else link.removeAttribute('aria-current');
        });
      });
    }, { rootMargin:'-18% 0px -55% 0px' });
    sections.forEach(section => sectionObserver.observe(section));
    const playbackObserver = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting) video.pause();
    }, { threshold:0 });
    playbackObserver.observe($('farm-video'));
  }

  const syncPlay = () => { playButton.hidden = !video.paused && !video.ended; };
  const attemptPlay = async () => {
    videoError.hidden = true;
    try { await video.play(); } catch { syncPlay(); }
  };
  playButton.addEventListener('click', attemptPlay);
  ['play','pause','ended'].forEach(event => video.addEventListener(event, syncPlay));
  video.addEventListener('error', () => { videoError.hidden = false; playButton.hidden = true; });
  const source = video.querySelector('source');
  if (source) source.addEventListener('error', () => { videoError.hidden = false; });
  $('retry-video').addEventListener('click', () => { videoError.hidden = true; playButton.hidden = false; video.load(); attemptPlay(); });

  function drawChart() {
    if (!analysis || !analysis.frames.length) return;
    const frames = analysis.frames;
    const max = Math.max(...frames.map(frame => frame.motionPercent), 1) * 1.12;
    const color = activeMode === 'activity' ? '#568e73' : activeMode === 'pattern' ? '#c29b56' : '#728eac';
    graphPoints = frames.map(frame => [4 + frame.t / analysis.duration * 312, 76 - frame.motionPercent / max * 70]);
    const points = graphPoints.map(point => point.join(',')).join(' ');
    const averageY = 76 - analysis.summary.averageMotionPercent / max * 70;
    $('analysis-chart').innerHTML = `<svg viewBox="0 0 320 80" preserveAspectRatio="none" aria-hidden="true"><path d="M0 25H320M0 55H320" fill="none" stroke="#edf0f3"/><polygon points="4,80 ${points} 316,80" fill="${color}" opacity=".08"/><line class="chart-average" x1="4" x2="316" y1="${averageY}" y2="${averageY}" stroke="#7e857e" stroke-width="1" stroke-dasharray="4 3"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/><line id="chart-cursor" x1="4" x2="4" y1="0" y2="80" stroke="${color}" stroke-width="1" opacity=".4"/><circle id="chart-point" cx="4" cy="76" r="3.5" fill="${color}"/></svg>`;
    const peakRatio = motionRatio(analysis.summary.peakMotionPercent);
    $('analysis-chart').setAttribute('aria-label', `시간에 따른 움직임이에요. 실선이 점선보다 높으면 이 영상 평균보다 움직임이 많은 때예요. ${analysis.summary.peakTime}초 무렵에 가장 많았어요.${peakRatio ? ` 영상 평균의 약 ${peakRatio}배였어요.` : ''}`);
  }
  function updateFrame() {
    if (!analysis) return;
    const time = video.currentTime || 0;
    const index = Math.max(0, Math.min(analysis.frames.length - 1, Math.floor(time / analysis.sampleInterval)));
    const frame = analysis.frames[index];
    const summary = analysis.summary;
    text('current-time', clock(time));
    if (activeMode === 'farm') {
      text('live-value', clock(summary.peakTime)); text('live-unit', ''); text('metric-label', '가장 많이 움직인 때');
    } else if (activeMode === 'activity') {
      const ratio = motionRatio(frame.motionPercent);
      text('live-value', ratio || '-'); text('live-unit', ratio ? '배' : ''); text('metric-label', '이 영상 평균과 비교');
    } else if (activeMode === 'density') {
      text('live-value', friendlyZone(frame.dominantZone)); text('live-unit', ''); text('metric-label', '지금 가장 많이 움직인 곳');
      text('stat-two-value', clock(time));
      $('live-value').style.fontSize = '30px';
      const maxZone = Math.max(...frame.zones, 0);
      [...$('zone-grid').children].forEach((cell, i) => {
        const intensity = maxZone > 0 ? frame.zones[i] / maxZone : 0;
        cell.style.background = `hsl(${145 - intensity * 105} ${22 + intensity * 35}% ${96 - intensity * 25}%)`;
        cell.querySelector('strong').textContent = intensity >= .67 ? '많음' : intensity >= .33 ? '중간' : '적음';
      });
    } else {
      text('live-value', clock(summary.peakTime)); text('live-unit', ''); text('metric-label', '가장 많이 움직인 때');
      const change = Number((frame.motionPercent - analysis.frames[Math.max(index - 1, 0)].motionPercent).toFixed(1));
      text('stat-two-value', change > 0 ? '늘었어요' : change < 0 ? '줄었어요' : '비슷해요');
    }
    if (activeMode !== 'density') $('live-value').style.fontSize = '';
    if (graphPoints[index] && $('chart-cursor')) {
      const [x,y] = graphPoints[index];
      $('chart-cursor').setAttribute('x1',x); $('chart-cursor').setAttribute('x2',x);
      $('chart-point').setAttribute('cx',x); $('chart-point').setAttribute('cy',y);
    }
  }
  function renderMode() {
    const mode = modes[activeMode];
    $('video-caption-block').hidden = activeMode === 'farm';
    text('video-caption-title', mode.caption);
    text('video-caption', mode.description);
    text('analysis-title',mode.analysis); text('analysis-tag',mode.tag); text('analysis-detail',mode.detail);
    $('zone-grid').hidden = activeMode !== 'density';
    $('zone-legend').hidden = activeMode !== 'density';
    $('chart-block').hidden = activeMode === 'density';
    if (!analysis) { $('analysis-chart').textContent = '영상 분석 내용을 불러오고 있어요.'; return; }
    const summary = analysis.summary;
    const peakRatio = motionRatio(summary.peakMotionPercent);
    const peakComparison = peakRatio ? `약 ${peakRatio}배` : '비교하기 어려워요';
    const duration = `${Math.round(analysis.duration)}초`;
    text('video-duration', `${duration} 영상`); text('chart-end', clock(Math.round(analysis.duration))); text('chart-title', '시간에 따른 움직임');
    if (activeMode === 'farm') {
      text('stat-one-label','영상 평균과 비교'); text('stat-one-value', peakComparison);
      text('stat-two-label','주로 움직인 곳'); text('stat-two-value',friendlyZone(summary.activeZoneLabel));
    } else if (activeMode === 'activity') {
      text('stat-one-label','가장 많이 움직인 때'); text('stat-one-value',clock(summary.peakTime));
      text('stat-two-label','그때는 영상 평균의'); text('stat-two-value',peakComparison);
    } else if (activeMode === 'density') {
      text('stat-one-label','영상에서 주로 움직인 곳'); text('stat-one-value',friendlyZone(summary.activeZoneLabel));
      text('stat-two-label','지금 보고 있는 때'); text('stat-two-value',clock(video.currentTime));
    } else {
      text('stat-one-label','가장 많을 때는 영상 평균의'); text('stat-one-value',peakComparison);
      text('stat-two-label','조금 전과 비교하면'); text('stat-two-value','비슷해요');
    }
    drawChart(); updateFrame();
  }
  $('zone-grid').innerHTML = zoneNames.map(name => `<div><span>${name}</span><strong>적음</strong></div>`).join('');
  async function selectMode(tab, autoplay = true) {
    const nextMode = tab.dataset.mode;
    if (nextMode === activeMode) { if (autoplay) attemptPlay(); return; }
    const token = ++mediaChange;
    const nearEnd = video.ended || (Number.isFinite(video.duration) && video.currentTime >= video.duration - .75);
    const seek = nearEnd ? 0 : (video.currentTime || 0);
    video.pause(); activeMode = nextMode; videoError.hidden = true;
    tabs.forEach(item => { const selected = item === tab; item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1; });
    $('video-panel').setAttribute('aria-labelledby',tab.id);
    video.poster = `/assets/jcr-${activeMode}-poster-v2.webp`;
    video.src = `/videos/jcr-${activeMode}-web-20261105.mp4`;
    video.setAttribute('aria-label',modes[activeMode].title + ' 영상');
    playButton.hidden = false;
    renderMode();
    const ready = () => {
      if (token !== mediaChange) return;
      if (Number.isFinite(video.duration)) video.currentTime = Math.min(seek, Math.max(0,video.duration - .2));
      if (autoplay) attemptPlay();
    };
    video.addEventListener('loadedmetadata',ready,{once:true});
    video.load();
  }
  tabs.forEach((tab,index) => {
    tab.addEventListener('click', () => selectMode(tab));
    tab.addEventListener('keydown',event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); selectMode(tabs[next]);
    });
  });
  video.addEventListener('timeupdate', updateFrame);
  video.addEventListener('seeked', updateFrame);
  function seekTo(seconds) {
    const seek = () => {
      video.currentTime = seconds;
      attemptPlay();
      updateFrame();
    };
    if (video.readyState >= 1) seek();
    else {
      video.addEventListener('loadedmetadata', seek, { once:true });
      video.load();
    }
    video.scrollIntoView({
      block:'center',
      behavior:matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth'
    });
  }
  document.querySelectorAll('[data-seek]').forEach(button => {
    button.addEventListener('click', () => seekTo(Number(button.dataset.seek)));
  });
  $('video-peak').addEventListener('click', () => {
    if (analysis) seekTo(analysis.summary.peakTime);
  });

  fetch('/assets/jcr-video-analysis-20261105.json?v=5-friendly').then(response => {
    if (!response.ok) throw new Error('analysis unavailable');
    return response.json();
  }).then(result => {
    if (!Array.isArray(result.frames) || !result.frames.length) throw new Error('no samples');
    analysis = result;
    const { averageMotionPercent, peakMotionPercent, peakTime, observation } = result.summary;
    if (averageMotionPercent > 0 && peakMotionPercent > 0) {
      const ratio = (peakMotionPercent / averageMotionPercent).toFixed(1);
      text('video-insight-title', `움직임이 가장 많았던 건 ${peakTime}초 무렵이에요.`);
      text('video-insight-reason', `앞뒤 장면을 비교해 보니 ${peakTime}초 무렵의 움직임이 이 영상 평균의 약 ${ratio}배로 가장 많았어요. 그래서 이 장면을 골랐어요.`);
      $('video-insight-reason').hidden = false;
      text('video-conclusion', '그래프가 높은 곳일수록 움직임이 많이 잡힌 장면이에요. 같은 영상 안에서 비교했어요.');
      $('video-conclusion').hidden = false;
      text('video-peak-label', `${peakTime}초 장면 보기`);
      $('video-peak').hidden = false;
    }
    if (observation) text('video-insight-description', observation);
    renderMode();
  }).catch(() => {
    $('analysis-chart').textContent = '영상 분석 내용을 불러오지 못했어요.';
    text('analysis-detail','새로고침해 보세요. 농장 영상은 그대로 볼 수 있어요.');
  });
  renderMode();

  let hiddenUntil = 0;
  try { hiddenUntil = Number(localStorage.getItem(noticeKey)) || 0; } catch { /* Show the notice without storage. */ }
  if (Date.now() >= hiddenUntil && !location.hash) {
    const scheduleNotice = () => {
      setTimeout(() => {
        if (!noticeOpened && !location.hash && window.scrollY < 50 && !dialogs.some(dialog => dialog.open)) showNotice();
      }, 1600);
    };
    const introAnimation = $('brand-intro').getAnimations?.()[0];
    if (introAnimation) introAnimation.finished.then(scheduleNotice, scheduleNotice);
    else scheduleNotice();
  }
})();
