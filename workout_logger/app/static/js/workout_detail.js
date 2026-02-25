(function () {
  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  function el(id) {
    return document.getElementById(id);
  }

  function formatDuration(secondsValue) {
    const total = Number(secondsValue);
    if (!Number.isFinite(total) || total < 0) return '';
    const whole = Math.floor(total);
    const minutes = Math.floor(whole / 60);
    const seconds = whole % 60;
    if (minutes && seconds) return `${minutes}m ${seconds}s`;
    if (minutes) return `${minutes}m`;
    return `${seconds}s`;
  }

  function renderPreviousSets(container, sets) {
    if (!sets || sets.length === 0) {
      container.innerHTML = '<p class="muted">No matching sets in previous workout.</p>';
      return;
    }
    const rows = sets.map((s) => {
      const rpe = s.rpe == null ? '' : s.rpe;
      const reps = s.reps == null ? '' : s.reps;
      const duration = s.duration_seconds == null ? '' : formatDuration(s.duration_seconds);
      return `<tr><td>${s.set_no}</td><td>${reps}</td><td>${duration}</td><td>${s.weight_kg}</td><td>${rpe}</td></tr>`;
    }).join('');
    container.innerHTML = `
      <table>
        <thead><tr><th>Set</th><th>Reps</th><th>Duration</th><th>Weight</th><th>RPE</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  document.addEventListener('DOMContentLoaded', function () {
    const panel = document.getElementById('exercise-hint-panel');
    const select = document.getElementById('exercise_id');
    const addSetForm = document.getElementById('add-set-form');
    const setNoInput = document.getElementById('set_no');
    const repsInput = document.getElementById('reps');
    const durationInput = document.getElementById('duration_seconds');
    const repsField = document.getElementById('reps-field');
    const durationField = document.getElementById('duration-field');
    const exerciseNameInput = document.getElementById('exercise_name');
    const planMeta = document.getElementById('exercise-plan-meta');
    if (!panel || !select) return;

    const hintExerciseName = el('hint-exercise-name');
    const previousMeta = el('hint-previous-meta');
    const previousSets = el('hint-previous-sets');
    const previousNote = el('hint-previous-note');
    const currentNote = el('current-exercise-note');
    const status = el('note-save-status');
    const storageKey = `workout_logger:last_exercise:${panel.dataset.workoutId}`;
    let activeExerciseId = null;

    async function fetchHint(exerciseId) {
      status.textContent = '';
      currentNote.disabled = true;
      hintExerciseName.textContent = 'Loading...';
      previousMeta.textContent = '';
      previousSets.innerHTML = '';
      previousNote.textContent = '';

      const url = new URL(panel.dataset.hintUrl, window.location.origin);
      url.searchParams.set('exercise_id', exerciseId);
      const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!response.ok) {
        throw new Error('Failed to load exercise hint');
      }
      return response.json();
    }

    async function saveNoteNow() {
      if (!activeExerciseId) return;
      status.textContent = 'Saving...';
      try {
        const response = await fetch(panel.dataset.noteUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
          body: JSON.stringify({ exercise_id: Number(activeExerciseId), note: currentNote.value })
        });
        if (!response.ok) throw new Error('Save failed');
        status.textContent = 'Saved';
      } catch (_err) {
        status.textContent = 'Save failed';
      }
    }

    const debouncedSave = debounce(saveNoteNow, 500);

    function selectedOption() {
      return select.options[select.selectedIndex] || null;
    }

    function updateExerciseMeta() {
      const option = selectedOption();
      if (!option || !option.value) {
        if (planMeta) planMeta.textContent = '';
        return;
      }
      const targetSets = option.dataset.targetSets;
      const targetReps = option.dataset.targetReps;
      const loggedSets = option.dataset.loggedSets;
      const parts = [];
      if (targetSets || targetReps) {
        const target = `${targetSets || ''}${targetSets && targetReps ? ' x ' : ''}${targetReps || ''}`.trim();
        if (target) parts.push(`Target: ${target}`);
      }
      if (loggedSets && targetSets) {
        parts.push(`Progress: ${loggedSets}/${targetSets} sets`);
      }
      const nextSet = option.dataset.nextSet;
      if (nextSet) {
        parts.push(`Next set #: ${nextSet}`);
      }
      if (planMeta) {
        planMeta.textContent = parts.join(' · ');
      }
    }

    function applySelectionDefaults() {
      const option = selectedOption();
      if (!option || !option.value) return;
      const targetMode = option.dataset.targetMode || 'reps';
      if (setNoInput && option.dataset.nextSet) {
        setNoInput.value = option.dataset.nextSet;
      }
      if (repsField) repsField.hidden = targetMode === 'duration';
      if (durationField) durationField.hidden = targetMode !== 'duration';
      if (repsInput) repsInput.required = targetMode !== 'duration';
      if (durationInput) durationInput.required = targetMode === 'duration';
      if (repsInput) {
        const suggestedReps = option.dataset.suggestedReps || '';
        if (targetMode !== 'duration' && suggestedReps) {
          const parsed = Number(suggestedReps);
          if (!Number.isNaN(parsed) && (repsInput.value === '' || repsInput.dataset.autofilled === '1')) {
            repsInput.value = String(parsed);
            repsInput.dataset.autofilled = '1';
          }
        } else if (repsInput.dataset.autofilled === '1' || targetMode === 'duration') {
          repsInput.value = '';
          repsInput.dataset.autofilled = '0';
        }
      }
      if (durationInput) {
        const suggestedDuration = option.dataset.suggestedDuration || '';
        if (targetMode === 'duration' && suggestedDuration) {
          durationInput.value = suggestedDuration;
          durationInput.readOnly = true;
        } else {
          durationInput.readOnly = false;
          durationInput.value = '';
        }
      }
      updateExerciseMeta();
    }

    async function handleExerciseChange() {
      const exerciseId = select.value;
      activeExerciseId = exerciseId || null;
      if (!exerciseId) {
        localStorage.removeItem(storageKey);
        hintExerciseName.textContent = 'No exercise selected';
        previousMeta.textContent = '';
        previousSets.innerHTML = '';
        previousNote.textContent = '';
        currentNote.value = '';
        currentNote.disabled = true;
        status.textContent = '';
        if (repsField) repsField.hidden = false;
        if (durationField) durationField.hidden = true;
        if (repsInput) repsInput.required = true;
        if (durationInput) {
          durationInput.required = false;
          durationInput.readOnly = false;
          durationInput.value = '';
        }
        updateExerciseMeta();
        return;
      }
      localStorage.setItem(storageKey, exerciseId);
      applySelectionDefaults();
      try {
        const data = await fetchHint(exerciseId);
        hintExerciseName.textContent = data.exercise || 'Exercise';
        if (data.previous) {
          previousMeta.textContent = `Previous: ${data.previous.workout_date} · ${data.previous.title}`;
          renderPreviousSets(previousSets, data.previous.sets || []);
        } else {
          previousMeta.textContent = 'No previous matching workout found';
          previousSets.innerHTML = '';
        }
        previousNote.textContent = data.previous_note || 'No previous note';
        currentNote.value = data.current_note || '';
        currentNote.disabled = false;
        status.textContent = 'Loaded';
      } catch (_err) {
        hintExerciseName.textContent = 'Error loading hint';
        previousMeta.textContent = '';
        previousSets.innerHTML = '';
        previousNote.textContent = '';
        currentNote.disabled = true;
        status.textContent = 'Failed to load';
      }
    }

    select.addEventListener('change', function () {
      if (exerciseNameInput && select.value) {
        exerciseNameInput.value = '';
      }
      void handleExerciseChange();
    });

    if (exerciseNameInput) {
      exerciseNameInput.addEventListener('input', function () {
        if (!exerciseNameInput.value.trim()) return;
        if (select.value) {
          select.value = '';
          localStorage.removeItem(storageKey);
          updateExerciseMeta();
        }
      });
    }

    if (repsInput) {
      repsInput.addEventListener('input', function () {
        repsInput.dataset.autofilled = '0';
      });
    }
    if (durationInput) {
      durationInput.addEventListener('input', function () {
        if (!durationInput.readOnly) {
          durationInput.dataset.manual = durationInput.value ? '1' : '';
        }
      });
    }

    currentNote.addEventListener('input', function () {
      if (!activeExerciseId) return;
      status.textContent = 'Typing...';
      debouncedSave();
    });

    if (addSetForm) {
      addSetForm.addEventListener('submit', function () {
        if (select.value) {
          localStorage.setItem(storageKey, select.value);
        }
      });
    }

    if (!select.value) {
      const remembered = localStorage.getItem(storageKey);
      const hasRememberedOption = Array.from(select.options).some((opt) => opt.value === remembered);
      if (remembered && hasRememberedOption) {
        select.value = remembered;
      }
    }

    if (select.value) {
      void handleExerciseChange();
    } else {
      updateExerciseMeta();
    }
  });
})();
