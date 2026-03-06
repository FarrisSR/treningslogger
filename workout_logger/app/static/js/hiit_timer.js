(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function clampInt(value, fallback, min) {
    const num = Number.parseInt(value, 10);
    if (!Number.isFinite(num)) return fallback;
    return Math.max(min, num);
  }

  function formatClock(totalSeconds) {
    const safe = Math.max(0, Math.ceil(totalSeconds));
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  function createAudio() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;
    return new AudioContextClass();
  }

  document.addEventListener('DOMContentLoaded', function () {
    const root = document.querySelector('[data-hiit-root]');
    if (!root) return;

    const form = byId('hiit-timer-form');
    const workInput = byId('work_seconds');
    const restInput = byId('rest_seconds');
    const cyclesInput = byId('cycles');
    const setsInput = byId('sets');
    const startBtn = byId('start-timer');
    const pauseBtn = byId('pause-timer');
    const resetBtn = byId('reset-timer');
    const display = byId('timer-display');
    const phaseLabel = byId('timer-phase-label');
    const clock = byId('timer-clock');
    const subLabel = byId('timer-sub-label');
    const progressBar = byId('timer-progress-bar');
    const summaryCycle = byId('summary-cycle');
    const summarySet = byId('summary-set');
    const summaryNext = byId('summary-next');
    const summaryTotal = byId('summary-total');
    const presetButtons = Array.from(document.querySelectorAll('[data-preset-work]'));
    const storageKey = 'workout_logger:hiit_timer_settings';

    let audioContext = null;
    let wakeLock = null;
    let timerId = null;
    let running = false;
    let phaseStartedAt = 0;
    let remainingMs = 0;
    let beepedSecond = null;
    let config = null;
    let state = null;

    function loadSettings() {
      try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return;
        const saved = JSON.parse(raw);
        workInput.value = clampInt(saved.work_seconds, 20, 1);
        restInput.value = clampInt(saved.rest_seconds, 10, 0);
        cyclesInput.value = clampInt(saved.cycles, 8, 1);
        setsInput.value = clampInt(saved.sets, 1, 1);
      } catch (_err) {}
    }

    function saveSettings() {
      const payload = readConfig();
      localStorage.setItem(storageKey, JSON.stringify(payload));
    }

    function readConfig() {
      return {
        work_seconds: clampInt(workInput.value, 20, 1),
        rest_seconds: clampInt(restInput.value, 10, 0),
        cycles: clampInt(cyclesInput.value, 8, 1),
        sets: clampInt(setsInput.value, 1, 1)
      };
    }

    function totalDurationSeconds(cfg) {
      const workSegments = cfg.work_seconds * cfg.cycles * cfg.sets;
      const restSegments = Math.max(0, (cfg.cycles * cfg.sets) - 1) * cfg.rest_seconds;
      return workSegments + restSegments;
    }

    function buildPhases(cfg) {
      const phases = [];
      for (let setNo = 1; setNo <= cfg.sets; setNo += 1) {
        for (let cycleNo = 1; cycleNo <= cfg.cycles; cycleNo += 1) {
          phases.push({
            kind: 'work',
            seconds: cfg.work_seconds,
            setNo,
            cycleNo,
            label: 'Trening'
          });
          const isLast = setNo === cfg.sets && cycleNo === cfg.cycles;
          if (!isLast && cfg.rest_seconds > 0) {
            phases.push({
              kind: 'rest',
              seconds: cfg.rest_seconds,
              setNo,
              cycleNo,
              label: 'Hvile'
            });
          }
        }
      }
      return phases;
    }

    function ensureAudioReady() {
      if (!audioContext) {
        audioContext = createAudio();
      }
      if (audioContext && audioContext.state === 'suspended') {
        audioContext.resume().catch(function () {});
      }
    }

    function beep(isFinal) {
      ensureAudioReady();
      if (!audioContext) return;
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      const now = audioContext.currentTime;
      osc.type = 'sine';
      osc.frequency.value = isFinal ? 1320 : 880;
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(isFinal ? 0.25 : 0.12, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + (isFinal ? 0.24 : 0.14));
      osc.connect(gain);
      gain.connect(audioContext.destination);
      osc.start(now);
      osc.stop(now + (isFinal ? 0.26 : 0.16));
    }

    async function requestWakeLock() {
      if (!('wakeLock' in navigator) || wakeLock) return;
      try {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', function () {
          wakeLock = null;
        });
      } catch (_err) {}
    }

    async function releaseWakeLock() {
      if (!wakeLock) return;
      try {
        await wakeLock.release();
      } catch (_err) {}
      wakeLock = null;
    }

    function currentPhase() {
      return state && state.phases[state.phaseIndex] ? state.phases[state.phaseIndex] : null;
    }

    function nextPhase() {
      return state && state.phases[state.phaseIndex + 1] ? state.phases[state.phaseIndex + 1] : null;
    }

    function render() {
      const phase = currentPhase();
      if (!config || !state || !phase) {
        const preview = readConfig();
        display.dataset.phase = 'ready';
        phaseLabel.textContent = 'Klar';
        clock.textContent = formatClock(preview.work_seconds);
        subLabel.textContent = 'Trykk start for å begynne';
        progressBar.style.width = '0%';
        summaryCycle.textContent = `1 / ${preview.cycles}`;
        summarySet.textContent = `1 / ${preview.sets}`;
        summaryNext.textContent = preview.rest_seconds > 0 ? 'Hvile' : 'Trening';
        summaryTotal.textContent = formatClock(totalDurationSeconds(preview));
        return;
      }

      const leftSeconds = remainingMs / 1000;
      const pct = phase.seconds > 0 ? ((phase.seconds - leftSeconds) / phase.seconds) * 100 : 100;
      display.dataset.phase = running ? phase.kind : 'ready';
      phaseLabel.textContent = running ? phase.label : 'Pause';
      clock.textContent = formatClock(leftSeconds);
      subLabel.textContent = `${phase.label} · sykel ${phase.cycleNo} av ${config.cycles} · sett ${phase.setNo} av ${config.sets}`;
      progressBar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
      summaryCycle.textContent = `${phase.cycleNo} / ${config.cycles}`;
      summarySet.textContent = `${phase.setNo} / ${config.sets}`;
      summaryNext.textContent = nextPhase() ? nextPhase().label : 'Ferdig';
      summaryTotal.textContent = formatClock(totalDurationSeconds(config));
    }

    function finishTimer() {
      running = false;
      window.clearInterval(timerId);
      timerId = null;
      display.dataset.phase = 'done';
      phaseLabel.textContent = 'Ferdig';
      clock.textContent = '00:00';
      subLabel.textContent = 'Økten er ferdig';
      progressBar.style.width = '100%';
      summaryNext.textContent = '-';
      beep(true);
      void releaseWakeLock();
    }

    function advancePhase() {
      state.phaseIndex += 1;
      const phase = currentPhase();
      beepedSecond = null;
      if (!phase) {
        finishTimer();
        return;
      }
      remainingMs = phase.seconds * 1000;
      phaseStartedAt = Date.now();
      render();
    }

    function tick() {
      const phase = currentPhase();
      if (!running || !phase) return;
      const elapsed = Date.now() - phaseStartedAt;
      remainingMs = Math.max(0, phase.seconds * 1000 - elapsed);
      const wholeSeconds = Math.ceil(remainingMs / 1000);
      if (wholeSeconds <= 5 && wholeSeconds >= 1 && wholeSeconds !== beepedSecond) {
        beep(wholeSeconds === 1);
        beepedSecond = wholeSeconds;
      }
      render();
      if (remainingMs <= 0) {
        advancePhase();
      }
    }

    function startTimer() {
      config = readConfig();
      saveSettings();
      if (!state || !state.phases || state.done) {
        state = {
          phases: buildPhases(config),
          phaseIndex: 0,
          done: false
        };
        const phase = currentPhase();
        remainingMs = phase ? phase.seconds * 1000 : 0;
      }
      ensureAudioReady();
      running = true;
      void requestWakeLock();
      phaseStartedAt = Date.now() - (((currentPhase() ? currentPhase().seconds * 1000 : 0) - remainingMs));
      window.clearInterval(timerId);
      timerId = window.setInterval(tick, 100);
      render();
    }

    function pauseTimer() {
      if (!running) return;
      running = false;
      window.clearInterval(timerId);
      timerId = null;
      void releaseWakeLock();
      render();
    }

    function resetTimer() {
      running = false;
      window.clearInterval(timerId);
      timerId = null;
      void releaseWakeLock();
      beepedSecond = null;
      config = readConfig();
      state = {
        phases: buildPhases(config),
        phaseIndex: 0,
        done: false
      };
      const phase = currentPhase();
      remainingMs = phase ? phase.seconds * 1000 : 0;
      render();
    }

    presetButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        workInput.value = btn.dataset.presetWork;
        restInput.value = btn.dataset.presetRest;
        cyclesInput.value = btn.dataset.presetCycles;
        setsInput.value = btn.dataset.presetSets;
        resetTimer();
      });
    });

    [workInput, restInput, cyclesInput, setsInput].forEach(function (input) {
      input.addEventListener('change', function () {
        if (!running) {
          resetTimer();
        }
      });
    });

    startBtn.addEventListener('click', startTimer);
    pauseBtn.addEventListener('click', pauseTimer);
    resetBtn.addEventListener('click', resetTimer);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      startTimer();
    });

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && running) {
        void requestWakeLock();
      }
    });

    loadSettings();
    resetTimer();
  });
})();
