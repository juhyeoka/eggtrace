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
    farm: { title:'농장 영상', caption:'농장 현장', description:'닭들이 지내는 모습을 담았습니다.', analysis:'영상 기록', tag:'현장 영상', detail:'앞뒤 장면의 변화를 비교했습니다. 그래프가 높을수록 움직임이 많이 잡힌 구간입니다.' },
    activity: { title:'활동량', caption:'움직임 표시', description:'움직임이 있는 곳을 초록색으로 표시합니다.', analysis:'활동량 분석', tag:'현재 장면', detail:'0.5초 전 장면과 비교해 달라진 화면 면적을 계산합니다. 비율이 높을수록 화면에서 잡힌 움직임이 많다는 뜻입니다.' },
    density: { title:'밀집도', caption:'움직임이 많은 곳', description:'움직임이 많을수록 노란색과 붉은색으로 나타납니다.', analysis:'구역별 분포', tag:'움직임 기준', detail:'화면을 9개 구역으로 나누고 각 구역의 변화를 비교합니다. 색이 진할수록 움직임이 많이 잡힌 곳이며 닭의 수를 뜻하지는 않습니다.' },
    pattern: { title:'패턴 변화', caption:'이동 방향', description:'화살표가 움직임의 방향을 나타냅니다.', analysis:'패턴 변화', tag:'시간별 분석', detail:'앞뒤 장면에서 움직인 방향을 비교했습니다. 화살표는 이동 방향을, 그래프는 시간에 따른 화면 변화량을 나타냅니다.' }
  };
  const zoneNames = ['좌측 상단','상단 중앙','우측 상단','좌측 중앙','중앙','우측 중앙','좌측 하단','하단 중앙','우측 하단'];
  let activeMode = 'farm';
  let analysis = null;
  let graphPoints = [];
  let mediaChange = 0;

  const certificates = {
    haccp: {
      description: '식품을 만들거나 포장하는 과정에서 위해 요소를 찾아 관리하는 기준입니다.',
      source: 'https://www.standard.go.kr/KSCI/crtfcSystem/searchCrtfcSystemView.do?crtfcstId=0000000470&crtfcstReformNo=0000&firstChk=ok&menuId=60373&topMenuId=536&upperMenuId=537&viewPage=system'
    },
    antibiotic: {
      description: '사료와 사육 관리가 무항생제축산물 기준에 맞는지 확인하는 인증입니다.',
      source: 'https://www.naqs.go.kr/hp/contents/contentsTab.do?menuId=MN20390'
    },
    sixth: {
      description: '지역 농산물 생산과 함께 가공이나 판매, 체험 사업을 운영하는 경영체에 주는 인증입니다.',
      source: 'https://xn--980b99s59h34f6tl.com/home/biz/company.cs?act=view&idx=4504'
    },
    naepo: {
      description: '내포천애는 홍성군의 농특산물 공동브랜드입니다.',
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
    $('video-caption-block').hidden = activeMode === 'farm';
    text('video-caption-title', mode.caption);
    text('video-caption', mode.description);
    text('analysis-title',mode.analysis); text('analysis-tag',mode.tag); text('analysis-detail',mode.detail);
    $('zone-grid').hidden = activeMode !== 'density';
    $('zone-legend').hidden = activeMode !== 'density';
    $('chart-block').hidden = activeMode === 'density';
    if (!analysis) { $('analysis-chart').textContent = '분석 데이터를 불러오는 중입니다.'; return; }
    const summary = analysis.summary;
    const duration = `${Math.round(analysis.duration)}초`;
    text('video-duration', `${duration} 영상`); text('chart-end', clock(Math.round(analysis.duration)));
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

  fetch('/assets/jcr-video-analysis-20261105.json?v=4-copy').then(response => {
    if (!response.ok) throw new Error('analysis unavailable');
    return response.json();
  }).then(result => {
    if (!Array.isArray(result.frames) || !result.frames.length) throw new Error('no samples');
    analysis = result;
    const { averageMotionPercent, peakMotionPercent, peakTime, observation } = result.summary;
    if (averageMotionPercent > 0 && peakMotionPercent > 0) {
      const ratio = (peakMotionPercent / averageMotionPercent).toFixed(1);
      text('video-insight-title', `${peakTime}초 무렵에 움직임이 가장 많이 잡혔습니다.`);
      text('video-insight-reason', `${result.sampleInterval}초 간격으로 앞뒤 장면이 얼마나 달라졌는지 비교했습니다. ${peakTime}초 무렵의 변화가 가장 컸고 이 영상 평균의 약 ${ratio}배여서 움직임이 가장 많은 장면으로 골랐습니다.`);
      $('video-insight-reason').hidden = false;
      text('video-conclusion', `움직임이 잡힌 화면의 비율은 평균 ${averageMotionPercent.toFixed(1)}%, ${peakTime}초 무렵에는 ${peakMotionPercent.toFixed(1)}%였습니다.`);
      $('video-conclusion').hidden = false;
      text('video-peak-label', `${peakTime}초 장면 보기`);
      $('video-peak').hidden = false;
    }
    if (observation) text('video-insight-description', observation);
    renderMode();
  }).catch(() => {
    $('analysis-chart').textContent = '분석 기록을 불러오지 못했습니다.';
    text('analysis-detail','다시 접속하면 분석 기록을 불러옵니다. 영상은 재생할 수 있습니다.');
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
