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
    farm: { title:'농장 영상', caption:'크로바 농장 현장', description:'닭들이 지내는 모습을 담았습니다.', analysis:'영상 기록', tag:'현장 영상', detail:'전체 영상의 움직임을 0.5초 간격으로 확인할 수 있습니다.' },
    activity: { title:'활동량', caption:'움직이는 구간 표시', description:'초록색 영역과 박스로 움직임이 잡힌 곳을 표시했습니다.', analysis:'활동량 분석', tag:'현재 장면', detail:'직전 프레임과 비교해 달라진 화면의 비율입니다.' },
    density: { title:'밀집도', caption:'움직임이 집중된 구역', description:'움직임이 많이 잡힌 곳일수록 노란색과 붉은색으로 표시됩니다.', analysis:'구역별 분포', tag:'움직임 기준', detail:'화면을 9개 구역으로 나눈 움직임 분포입니다.' },
    pattern: { title:'패턴 변화', caption:'이동 흐름과 시간별 변화', description:'화살표는 이동 흐름, 그래프는 시간별 움직임을 보여줍니다.', analysis:'패턴 변화', tag:'시간별 분석', detail:'움직임이 가장 컸던 구간과 시간에 따른 변화를 확인하세요.' }
  };
  const zoneNames = ['좌측 상단','상단 중앙','우측 상단','좌측 중앙','중앙','우측 중앙','좌측 하단','하단 중앙','우측 하단'];
  let activeMode = 'farm';
  let analysis = null;
  let graphPoints = [];
  let toastTimer;
  let mediaChange = 0;
  const notify = message => {
    clearTimeout(toastTimer);
    $('toast').textContent = message;
    $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3000);
  };

  text('summary-status', data.hasData ? `${data.recordCount}건의 분석 기록` : '등록된 기록이 없습니다.');
  text('latest-record', data.latestLabel);
  text('record-count', data.hasData ? `${data.recordCount}건` : '미등록');
  text('motion-summary', data.hasData ? `${data.averageMotionPercent}%` : '미등록');
  const dates = data.periodLabel.match(/\d{4}\.\d{2}\.\d{2}/g) || [];
  text('record-period-short', dates.length ? dates.map(date => date.slice(5)).join(' ~ ') : '미등록');
  document.querySelector('.record-date').title = data.periodLabel;

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
  document.querySelectorAll('[data-cert-image]').forEach(button => button.addEventListener('click', () => {
    text('cert-dialog-title', button.dataset.certTitle);
    $('cert-dialog-image').src = button.dataset.certImage;
    $('cert-dialog-image').alt = button.dataset.certTitle;
    openDialog($('cert-dialog'));
  }));
  const notice = $('farm-notice');
  const noticeKey = 'eggtrace:farm-notice:20261105:hidden-until';
  $('notice-hide').addEventListener('click', () => {
    try { localStorage.setItem(noticeKey, String(Date.now() + 86400000)); } catch { /* Closing is available without storage. */ }
    notice.close();
  });
  $('reopen-notice').addEventListener('click', () => openDialog(notice));

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
    $('analysis-chart').innerHTML = `<svg viewBox="0 0 320 80" aria-hidden="true"><path d="M0 25H320M0 55H320" fill="none" stroke="#edf0f3"/><polygon points="4,80 ${points} 316,80" fill="${color}" opacity=".08"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round"/><line id="chart-cursor" x1="4" x2="4" y1="0" y2="80" stroke="${color}" stroke-width="1" opacity=".4"/><circle id="chart-point" cx="4" cy="76" r="3.5" fill="${color}"/></svg>`;
    $('analysis-chart').setAttribute('aria-label', `영상 전체 움직임. 평균 ${analysis.summary.averageMotionPercent}%, 최대 ${analysis.summary.peakMotionPercent}%, 최대 시점 ${analysis.summary.peakTime}초.`);
  }
  function updateFrame() {
    if (!analysis) return;
    const time = video.currentTime || 0;
    const index = Math.max(0, Math.min(analysis.frames.length - 1, Math.floor(time / analysis.sampleInterval)));
    const frame = analysis.frames[index];
    const summary = analysis.summary;
    text('current-time', clock(time));
    if (activeMode === 'farm') {
      text('live-value', Math.round(analysis.duration)); text('live-unit', '초'); text('metric-label', '전체 영상 길이');
    } else if (activeMode === 'activity') {
      text('live-value', frame.motionPercent.toFixed(1)); text('live-unit', '%'); text('metric-label', `${clock(time)} 현재 장면의 움직임`);
    } else if (activeMode === 'density') {
      text('live-value', frame.dominantZone); text('live-unit', ''); text('metric-label', '움직임이 가장 많이 잡힌 구역');
      $('live-value').style.fontSize = '30px';
      const maxZone = Math.max(...frame.zones, 1);
      [...$('zone-grid').children].forEach((cell, i) => {
        const intensity = frame.zones[i] / maxZone;
        cell.style.background = `hsl(${145 - intensity * 105} ${22 + intensity * 35}% ${96 - intensity * 25}%)`;
        cell.querySelector('strong').textContent = frame.zones[i].toFixed(1) + '%';
      });
    } else {
      text('live-value', clock(summary.peakTime)); text('live-unit', ''); text('metric-label', '움직임이 가장 컸던 시점');
      text('stat-two-value', `${(frame.motionPercent - (analysis.frames[Math.max(index - 1, 0)].motionPercent)).toFixed(1)}%p`);
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
    text('video-mode-label', mode.title); text('video-caption-title', mode.caption); text('video-caption', mode.description);
    text('analysis-title',mode.analysis); text('analysis-tag',mode.tag); text('analysis-detail',mode.detail);
    $('zone-grid').hidden = activeMode !== 'density';
    $('zone-legend').hidden = activeMode !== 'density';
    $('chart-block').hidden = activeMode === 'density';
    if (!analysis) { $('analysis-chart').textContent = '분석 데이터를 불러오는 중입니다.'; return; }
    const summary = analysis.summary;
    const duration = `${Math.round(analysis.duration)}초`;
    text('video-duration', duration); text('chart-end', clock(Math.round(analysis.duration)));
    if (activeMode === 'farm') {
      text('stat-one-label','평균 움직임'); text('stat-one-value', `${summary.averageMotionPercent.toFixed(1)}%`);
      text('stat-two-label','주요 활동 구역'); text('stat-two-value',summary.activeZoneLabel);
    } else if (activeMode === 'activity') {
      text('stat-one-label','영상 평균'); text('stat-one-value',`${summary.averageMotionPercent.toFixed(1)}%`);
      text('stat-two-label','최대 움직임'); text('stat-two-value',`${summary.peakMotionPercent.toFixed(1)}%`);
    } else if (activeMode === 'density') {
      text('stat-one-label','전체 영상 주요 구역'); text('stat-one-value',summary.activeZoneLabel);
      text('stat-two-label','분석 구역'); text('stat-two-value','9개');
    } else {
      text('stat-one-label','최대 움직임'); text('stat-one-value',`${summary.peakMotionPercent.toFixed(1)}%`);
      text('stat-two-label','직전 구간 대비'); text('stat-two-value','0.0%p');
    }
    drawChart(); updateFrame();
  }
  $('zone-grid').innerHTML = zoneNames.map(name => `<div><span>${name}</span><strong>0%</strong></div>`).join('');
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
  document.querySelectorAll('[data-seek]').forEach(button => button.addEventListener('click', () => {
    const seek = () => { video.currentTime = Number(button.dataset.seek); attemptPlay(); updateFrame(); };
    if (video.readyState >= 1) seek();
    else { video.addEventListener('loadedmetadata',seek,{once:true}); video.load(); }
    video.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth'});
  }));
  fetch('/assets/jcr-video-analysis-20261105.json').then(response => {
    if (!response.ok) throw new Error('analysis unavailable');
    return response.json();
  }).then(result => {
    if (!Array.isArray(result.frames) || !result.frames.length) throw new Error('no samples');
    analysis = result;
    if (data.productCode === 'EGG-0001') {
      text('summary-status', '농장 영상 요약');
      const labels = document.querySelectorAll('.summary-stats span');
      labels[0].textContent = '평균 움직임';
      labels[1].textContent = '주요 활동 구역';
      labels[2].textContent = '영상 길이';
      text('motion-summary', `${result.summary.averageMotionPercent.toFixed(1)}%`);
      text('record-count', result.summary.activeZoneLabel);
      text('record-period-short', `${Math.round(result.duration)}초`);
      document.querySelector('.record-date').textContent = '등록된 농장 영상 기준';
    }
    renderMode();
  }).catch(() => {
    $('analysis-chart').textContent = '분석 기록을 불러오지 못했습니다.';
    text('analysis-detail','다시 접속하면 분석 기록을 불러옵니다. 영상은 재생할 수 있습니다.');
  });
  renderMode();

  $('share-report').addEventListener('click', async () => {
    const url = new URL(location.href); url.hash = 'farm';
    if (navigator.share) {
      try { await navigator.share({title:'크로바 농장',url:url.href}); } catch (error) { if (error.name !== 'AbortError') notify('주소창의 링크를 복사해주세요.'); }
    } else {
      try { await navigator.clipboard.writeText(url.href); notify('링크를 복사했습니다.'); } catch { notify('주소창의 링크를 복사해주세요.'); }
    }
  });
  let hiddenUntil = 0;
  try { hiddenUntil = Number(localStorage.getItem(noticeKey)) || 0; } catch { /* Show the notice without storage. */ }
  if (Date.now() >= hiddenUntil) openDialog(notice);
})();
