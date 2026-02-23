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

  function renderPreviousSets(container, sets) {
    if (!sets || sets.length === 0) {
      container.innerHTML = '<p class="muted">No matching sets in previous workout.</p>';
      return;
    }
    const rows = sets.map((s) => {
      const rpe = s.rpe == null ? '' : s.rpe;
      return `<tr><td>${s.set_no}</td><td>${s.reps}</td><td>${s.weight_kg}</td><td>${rpe}</td></tr>`;
    }).join('');
    container.innerHTML = `
      <table>
        <thead><tr><th>Set</th><th>Reps</th><th>Weight</th><th>RPE</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  document.addEventListener('DOMContentLoaded', function () {
    const panel = document.getElementById('exercise-hint-panel');
    const select = document.getElementById('exercise_id');
    if (!panel || !select) return;

    const hintExerciseName = el('hint-exercise-name');
    const previousMeta = el('hint-previous-meta');
    const previousSets = el('hint-previous-sets');
    const previousNote = el('hint-previous-note');
    const currentNote = el('current-exercise-note');
    const status = el('note-save-status');
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

    select.addEventListener('change', async function () {
      const exerciseId = select.value;
      activeExerciseId = exerciseId || null;
      if (!exerciseId) {
        hintExerciseName.textContent = 'No exercise selected';
        previousMeta.textContent = '';
        previousSets.innerHTML = '';
        previousNote.textContent = '';
        currentNote.value = '';
        currentNote.disabled = true;
        status.textContent = '';
        return;
      }
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
    });

    currentNote.addEventListener('input', function () {
      if (!activeExerciseId) return;
      status.textContent = 'Typing...';
      debouncedSave();
    });
  });
})();
