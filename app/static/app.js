const state = {
  questions: [],
  selectedId: null,
  mediaRecorder: null,
  chunks: [],
  stream: null,
  timerId: null,
  startedAt: 0,
  audioUrl: null,
  speechRecognition: null,
  speechActive: false,
  analysis: null,
  pollId: null,
  result_panel: null,
  teacher: null,
  teacherData: null,
  student: null,
  hosted: false,
};

const el = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
})[char]);
const percent = (value) => `${Math.round((value || 0) * 100)} %`;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || `Erreur ${response.status}`);
  return payload;
}

function showMessage(text, type = "error") {
  const node = el("message");
  node.textContent = text;
  node.className = `inline-message ${type === "success" ? "success" : ""}`;
  node.hidden = !text;
}

function toast(text) {
  const node = el("toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(node.timeout);
  node.timeout = setTimeout(() => { node.hidden = true; }, 4200);
}

function setStep(step) {
  document.querySelectorAll(".step").forEach((node) => {
    node.classList.toggle("active", Number(node.dataset.step) <= step);
  });
}

function selectedQuestion() {
  return state.questions.find((question) => question.id === state.selectedId);
}

function cleanIdentityValue(input) {
  return String(input.value).trim().replace(/\s+/g, " ");
}

function validateIdentity() {
  const fields = [el("student-last-name"), el("student-first-name"), el("student-class")];
  fields.forEach((input) => {
    input.value = cleanIdentityValue(input);
    input.setAttribute("aria-invalid", String(!input.value));
  });
  const firstInvalid = fields.find((input) => !input.value);
  const error = el("identity-error");
  error.hidden = !firstInvalid;
  error.textContent = firstInvalid ? "Renseigne ton nom, ton prénom et ta classe pour continuer." : "";
  if (firstInvalid) firstInvalid.focus();
  return !firstInvalid;
}

function showWelcome() {
  el("welcome-view").hidden = false;
  el("assessment-view").hidden = true;
  el("teacher-login-view").hidden = true;
  el("teacher-dashboard-view").hidden = true;
  document.body.classList.remove("teacher-mode");
  el("student-chip").hidden = true;
  el("reset-button").hidden = true;
  setStep(0);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showTeacherLogin() {
  el("welcome-view").hidden = true;
  el("assessment-view").hidden = true;
  el("teacher-dashboard-view").hidden = true;
  el("teacher-login-view").hidden = false;
  document.body.classList.add("teacher-mode");
  el("student-chip").hidden = true;
  el("reset-button").hidden = true;
  setStep(0);
  window.scrollTo({ top: 0, behavior: "smooth" });
  setTimeout(() => el("teacher-code").focus(), 0);
}

function showAssessment() {
  el("welcome-view").hidden = true;
  el("assessment-view").hidden = false;
  el("teacher-login-view").hidden = true;
  el("teacher-dashboard-view").hidden = true;
  document.body.classList.remove("teacher-mode");
  el("student-chip").hidden = false;
  el("student-chip-name").textContent = `${state.student.first_name} ${state.student.last_name} · ${state.student.class_name}`;
  el("reset-button").hidden = false;
  setStep(1);
  el("level-filter").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetIdentityForm() {
  [el("student-last-name"), el("student-first-name"), el("student-class")].forEach((input) => {
    input.value = "";
    input.removeAttribute("aria-invalid");
  });
  el("identity-error").hidden = true;
  el("identity-error").textContent = "";
}

function populateFilters(payload) {
  for (const [level, theme] of [["level-filter", payload.levels], ["theme-filter", payload.themes]]) {
    const select = el(level);
    for (const value of theme) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
  }
}

function filteredQuestions() {
  const level = el("level-filter").value;
  const theme = el("theme-filter").value;
  return state.questions.filter((question) =>
    (!level || question.level === level) && (!theme || question.theme === theme));
}

function renderQuestions() {
  const questions = filteredQuestions();
  el("question-count").textContent = `${questions.length} / ${state.questions.length}`;
  el("question-list").innerHTML = questions.length ? questions.map((question) => `
    <button class="question-card ${question.id === state.selectedId ? "selected" : ""}" data-question-id="${escapeHtml(question.id)}" type="button">
      <span class="meta"><span>${escapeHtml(question.level)}</span><span>${escapeHtml(question.theme)}</span></span>
      <strong>${escapeHtml(question.title)}</strong>
      <small>${escapeHtml(question.prompt)}</small>
    </button>`).join("") : `<p class="source-note">Aucune question pour ces filtres.</p>`;
  el("question-list").querySelectorAll("[data-question-id]").forEach((button) => {
    button.addEventListener("click", () => selectQuestion(button.dataset.questionId));
  });
}

function selectQuestion(questionId) {
  const question = state.questions.find((item) => item.id === questionId);
  if (!question) return;
  state.selectedId = questionId;
  state.analysis = null;
  el("focus-level").textContent = question.level;
  el("focus-theme").textContent = question.theme;
  el("selected-title").textContent = question.prompt;
  el("selected-context").textContent = question.context;
  el("selected-answer").textContent = question.expected_answer;
  el("transcript").value = "";
  el("transcript").disabled = false;
  el("analyze-button").disabled = true;
  el("record-button").disabled = false;
  el("record-button").classList.remove("recording");
  el("record-title").textContent = state.hosted ? "Prêt à dicter" : "Prêt à écouter";
  el("record-help").textContent = "Réponse conseillée : 10 à 30 secondes";
  el("audio-preview").hidden = true;
  clearAudio();
  showMessage("");
  resetResult();
  renderQuestions();
  setStep(2);
  if (window.innerWidth < 1220) document.querySelector(".answer-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function clearAudio() {
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = null;
}

function updateTranscriptState() {
  const text = el("transcript").value.trim();
  const words = text ? text.split(/\s+/).length : 0;
  el("transcript-count").textContent = `${words} mot${words > 1 ? "s" : ""}`;
  el("analyze-button").disabled = !state.selectedId || !text;
}

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function startBrowserDictation() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    toast("Ce navigateur ne propose pas la dictée. Saisis directement la réponse dans le champ.");
    return;
  }
  if (!state.selectedId) {
    toast("Choisis d’abord une question.");
    return;
  }
  const recognition = new Recognition();
  recognition.lang = "fr-FR";
  recognition.continuous = true;
  recognition.interimResults = true;
  let finalText = "";
  recognition.onresult = (event) => {
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const text = event.results[index][0].transcript;
      if (event.results[index].isFinal) finalText += `${text} `;
      else interim += text;
    }
    el("transcript").value = `${finalText}${interim}`.trim();
    el("transcript-count").textContent = `${el("transcript").value.split(/\s+/).filter(Boolean).length} mots`;
    updateTranscriptState();
  };
  recognition.onerror = (event) => {
    if (!["aborted", "no-speech"].includes(event.error)) toast(`Dictée interrompue : ${event.error}.`);
  };
  recognition.onend = () => {
    state.speechRecognition = null;
    state.speechActive = false;
    el("record-button").classList.remove("recording");
    el("record-button").setAttribute("aria-label", "Démarrer la dictée");
    el("record-title").textContent = finalText.trim() ? "Dictée terminée" : "Dictée arrêtée";
    el("record-help").textContent = "Relis la transcription avant l’analyse";
  };
  try {
    recognition.start();
    state.speechRecognition = recognition;
    state.speechActive = true;
    el("record-button").classList.add("recording");
    el("record-button").setAttribute("aria-label", "Arrêter la dictée");
    el("record-title").textContent = "Dictée en cours…";
    el("record-help").textContent = "Parle naturellement, en une ou deux phrases";
  } catch {
    toast("La dictée n’a pas pu démarrer. Saisis la réponse dans le champ.");
  }
}

async function toggleRecording() {
  if (state.speechActive) {
    state.speechRecognition?.stop();
    return;
  }
  if (state.mediaRecorder?.state === "recording") {
    state.mediaRecorder.stop();
    return;
  }
  if (state.hosted) {
    startBrowserDictation();
    return;
  }
  if (!state.selectedId) {
    toast("Choisissez d’abord une question.");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast("Ce navigateur ne permet pas l’enregistrement. Importez un fichier audio.");
    return;
  }
  try {
    showMessage("");
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mimeType = MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
    state.chunks = [];
    state.mediaRecorder = new MediaRecorder(state.stream, mimeType ? { mimeType } : undefined);
    state.mediaRecorder.ondataavailable = (event) => { if (event.data.size) state.chunks.push(event.data); };
    state.mediaRecorder.onstop = handleRecordedAudio;
    state.mediaRecorder.start(250);
    state.startedAt = Date.now();
    el("record-button").classList.add("recording");
    el("record-button").setAttribute("aria-label", "Arrêter l’enregistrement");
    el("record-title").textContent = "Écoute en cours…";
    el("record-help").textContent = "Répondez naturellement, en une ou deux phrases";
    el("timer").hidden = false;
    state.timerId = setInterval(updateTimer, 250);
  } catch (error) {
    toast("Microphone inaccessible. Autorisez le micro ou importez un audio.");
    stopStream();
  }
}

function updateTimer() {
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  el("timer").textContent = `00:${String(Math.min(seconds, 99)).padStart(2, "0")}`;
  if (seconds >= 45) {
    toast("Limite de 45 secondes atteinte.");
    if (state.mediaRecorder?.state === "recording") state.mediaRecorder.stop();
  }
}

function stopStream() {
  state.stream?.getTracks().forEach((track) => track.stop());
  state.stream = null;
  clearInterval(state.timerId);
  state.timerId = null;
  el("timer").hidden = true;
  el("record-button").classList.remove("recording");
  el("record-button").setAttribute("aria-label", state.hosted ? "Démarrer la dictée" : "Démarrer l'enregistrement");
}

async function handleRecordedAudio() {
  stopStream();
  const type = state.mediaRecorder?.mimeType || "audio/webm";
  const blob = new Blob(state.chunks, { type });
  if (!blob.size) {
    toast("Aucun son enregistré. Réessayez.");
    return;
  }
  clearAudio();
  state.audioUrl = URL.createObjectURL(blob);
  el("audio-player").src = state.audioUrl;
  el("audio-preview").hidden = false;
  el("record-title").textContent = "Réponse enregistrée";
  el("record-help").textContent = "Transcription locale en cours…";
  await transcribeBlob(blob, "reponse.webm");
}

async function handleUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (state.hosted) {
    event.target.value = "";
    toast("La transcription des fichiers audio est disponible dans la version locale de Voix SVT.");
    return;
  }
  clearAudio();
  state.audioUrl = URL.createObjectURL(file);
  el("audio-player").src = state.audioUrl;
  el("audio-preview").hidden = false;
  el("record-title").textContent = "Audio importé";
  el("record-help").textContent = "Transcription locale en cours…";
  await transcribeBlob(file, file.name);
  event.target.value = "";
}

async function transcribeBlob(blob, filename) {
  el("transcript").disabled = true;
  const data = new FormData();
  data.append("file", blob, filename);
  try {
    const result = await api("/api/transcribe", { method: "POST", body: data });
    el("transcript").value = result.text;
    el("record-title").textContent = "Transcription prête";
    el("record-help").textContent = `Modèle ${result.model} · français`;
    showMessage("Vérifiez la transcription avant de lancer l’analyse.", "success");
    setStep(2);
  } catch (error) {
    el("record-title").textContent = "Transcription impossible";
    el("record-help").textContent = "Vous pouvez saisir la réponse manuellement";
    showMessage(error.message);
  } finally {
    el("transcript").disabled = false;
    updateTranscriptState();
  }
}



function resetResult() {
  clearTimeout(state.pollId);
  state.pollId = null;
  el("result-empty").hidden = false;
  el("result-content").hidden = true;
  el("result-content").innerHTML = "";
  el("engine-badge").textContent = "EN ATTENTE";
  el("engine-badge").classList.remove("ready");
  setStep(state.selectedId ? 2 : 1);
}

function criterionItem(item, found) {
  return `<div class="check-item ${found ? "found" : "missing"}"><i>${found ? "✓" : "–"}</i><span>${escapeHtml(item.label)}</span></div>`;
}

function layaMarkup(laya) {
  if (laya?.status === "disabled") {
    return `<div class="laya-card"><div class="laya-head"><b>Analyse complémentaire désactivée</b><span>NON UTILISÉ</span></div><p>Seule la grille déterministe a été utilisée pour cette réponse.</p></div>`;
  }
  if (!laya || laya.status === "queued") {
    return `<div class="laya-card loading"><span class="spinner"></span><span>Laya analyse la justesse et la complétude en arrière-plan.</span></div>`;
  }
  if (laya.status === "unavailable" || laya.status === "error") {
    return `<div class="laya-card"><div class="laya-head"><b>${escapeHtml(laya.decision_label)}</b><span>INDICE</span></div><p>${escapeHtml(laya.summary)}</p></div>`;
  }
  const science = laya.metrics.scientificite || {};
  const complete = laya.metrics.completude || {};
  return `<div class="laya-card">
    <div class="laya-head"><b>${escapeHtml(laya.decision_label)}</b><span>NON NOTANT</span></div>
    <p>${escapeHtml(laya.summary)}</p>
    <div class="metric-pair">
      <div class="metric"><small>JUSTESSE · P(vrai)</small><b>${percent(science.probabilite_vrai)}</b></div>
      <div class="metric"><small>COMPLÉTUDE · P(vrai)</small><b>${percent(complete.probabilite_vrai)}</b></div>
    </div>
  </div>`;
}

function remediationMarkup(remediation) {
  return `<div class="remediation-card">
    <span>ACTIVITÉ CIBLÉE · 3–5 MIN</span>
    <h4>${escapeHtml(remediation.title)}</h4>
    <p>${escapeHtml(remediation.focus)}</p>
    <ol class="remediation-steps">${remediation.steps.map((step) => `<li><span>${escapeHtml(step)}</span></li>`).join("")}</ol>
    <div class="retry-box"><b>Réponse à réessayer</b>${escapeHtml(remediation.retry_prompt)}</div>
  </div>`;
}

function sheetsStatus(sheetsState = {}) {
  if (sheetsState.status === "sent") return "ENVOYÉ";
  if (sheetsState.status === "queued") return "EN ATTENTE";
  if (sheetsState.status === "error") return "À RÉESSAYER";
  return "NON CONFIGURÉ";
}

function sheetsMarkup(sheetsState = {}) {
  if (sheetsState.status === "sent") {
    return `<div class="export-status sent"><b>✓</b><div><strong>Résultat ajouté à Google Sheets</strong><span>${escapeHtml(sheetsState.message || "Enregistrement confirmé.")}</span></div></div>`;
  }
  if (sheetsState.status === "queued") {
    return `<div class="export-status"><span class="spinner"></span><div><strong>Enregistrement en cours</strong><span>Le résultat est transmis en arrière-plan.</span></div></div>`;
  }
  if (sheetsState.status === "error") {
    return `<div class="export-status error"><b>!</b><div><strong>Export Google indisponible</strong><span>${escapeHtml(sheetsState.message || "Vérifiez le déploiement Apps Script.")}</span></div></div>`;
  }
  return `<div class="export-status muted"><b>—</b><div><strong>Export non configuré</strong><span>${escapeHtml(sheetsState.message || "Renseignez GOOGLE_SHEETS_APP_URL avant de lancer le serveur.")}</span></div></div>`;
}

function renderAnalysis(analysis) {
  state.analysis = analysis;
  const result = analysis.deterministic;
  const question = analysis.question;
  const allCriteria = [...result.matched_criteria.map((item) => [item, true]), ...result.missing_criteria.map((item) => [item, false])];
  const misconceptions = result.misconceptions.map((item) => `<div class="misconception-alert"><b>${escapeHtml(item.label)}</b>${escapeHtml(item.feedback)}</div>`).join("");
  el("result-empty").hidden = true;
  el("result-content").hidden = false;
  el("engine-badge").textContent = result.contradictory ? "À CORRIGER" : "GRILLE RAPIDE";
  el("engine-badge").classList.add("ready");
  el("result-content").innerHTML = `
    <section class="score-hero">
      <div class="score-top">
        <div class="score-level">${result.level}<small> / ${result.max_level}</small></div>
        <div class="score-status"><b>${escapeHtml(result.label)}</b><span>${percent(result.coverage)} de la grille</span></div>
      </div>
      <div class="progress-track"><i style="width:${percent(result.coverage)}"></i></div>
      <p class="score-feedback">${escapeHtml(result.feedback)}</p>
    </section>
    <section class="result-section">
      <h3>Grille de mots <span>${result.matched_criteria.length}/${allCriteria.length} TROUVÉS</span></h3>
      <div class="check-list">${allCriteria.map(([item, found]) => criterionItem(item, found)).join("")}</div>
      ${misconceptions}
    </section>
    <section class="result-section"><h3>Décision Laya <span>INDICE COMPLEMENTAIRE</span></h3>${layaMarkup(analysis.laya)}</section>
    <section class="result-section"><h3>Remédiation proposée <span>CIBLE : ${escapeHtml(question.theme).toUpperCase()}</span></h3>${remediationMarkup(result.remediation)}</section>
    <section class="result-section">
      <h3>Correction savante <span>RÉFÉRENCE</span></h3>
      <div class="reference-block">${escapeHtml(question.expected_answer)}</div>
      <p class="source-line">Source : ${escapeHtml(question.source.file)} · ${escapeHtml(question.source.locator)}</p>
    </div>
    <div class="result-section">
      <h3>Enregistrement du résultat <span>${escapeHtml(sheetsStatus(analysis.sheets))}</span></h3>
      ${sheetsMarkup(analysis.sheets)}
    </div>
  `;
  setStep(3);
  if (analysis.laya.status === "queued" || analysis.sheets.status === "queued") pollAnalysis(analysis.id);
}


async function analyzeAnswer() {
  if (!state.student) {
    toast("Renseigne d’abord la fiche élève.");
    showWelcome();
    return;
  }
  const transcription = el("transcript").value.trim();
  if (!state.selectedId || !transcription) return;
  const button = el("analyze-button");
  button.disabled = true;
  button.querySelector("span").textContent = "Analyse en cours…";
  showMessage("");
  try {
    const analysis = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question_id: state.selectedId,
        transcription,
        use_laya: el("laya-toggle").checked,
        student_first_name: state.student.first_name,
        student_last_name: state.student.last_name,
        student_class: state.student.class_name,
      }),
    });
    renderAnalysis(analysis);
    showMessage("Correction déterministe terminée. Laya complète l’analyse si nécessaire.", "success");
  } catch (error) {
    showMessage(error.message);
  } finally {
    button.querySelector("span").textContent = "Analyser la réponse";
    updateTranscriptState();
  }
}

function pollAnalysis(analysisId) {
  clearTimeout(state.pollId);
  state.pollId = setTimeout(async () => {
    try {
      const analysis = await api(`/api/analysis/${analysisId}`);
      if (state.analysis?.id !== analysisId) return;
      renderAnalysis(analysis);
      if (analysis.laya.status === "queued" || analysis.sheets.status === "queued") pollAnalysis(analysisId);
    } catch (error) {
      toast(`Complément Laya indisponible : ${error.message}`);
    }
  }, 1800);
}

async function loginTeacher(event) {
  event.preventDefault();
  const input = el("teacher-code");
  const button = el("teacher-login-button");
  const error = el("teacher-login-error");
  const code = String(input.value || "").trim();
  if (!code) {
    error.textContent = "Saisissez le code enseignant.";
    error.hidden = false;
    input.focus();
    return;
  }
  button.disabled = true;
  button.querySelector("span").textContent = "Vérification…";
  error.hidden = true;
  try {
    const response = await fetch("/api/teacher/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_code: code }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Connexion impossible.");
    input.value = "";
    state.teacher = { authenticated: true };
    await loadTeacherData();
    showTeacherDashboard();
  } catch (requestError) {
    error.textContent = requestError.message || "Code incorrect.";
    error.hidden = false;
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Ouvrir le registre";
  }
}

async function logoutTeacher() {
  try { await api("/api/teacher/logout", { method: "POST" }); } catch { /* le cookie peut déjà être absent */ }
  state.teacher = null;
  state.teacherData = null;
  showWelcome();
}

async function loadTeacherData() {
  const button = el("teacher-import-button");
  const message = el("teacher-import-message");
  button.disabled = true;
  button.textContent = "Import en cours…";
  message.textContent = "Lecture du registre Google Sheets…";
  message.className = "teacher-import-message loading";
  try {
    state.teacherData = await api("/api/teacher/import", { method: "POST" });
    const count = state.teacherData.records.length;
    message.textContent = `${count} résultat${count > 1 ? "s" : ""} importé${count > 1 ? "s" : ""} · ${formatDateTime(state.teacherData.imported_at)}`;
    message.className = "teacher-import-message success";
    renderTeacherDashboard();
  } catch (requestError) {
    state.teacherData = null;
    message.textContent = requestError.message;
    message.className = "teacher-import-message error";
    renderTeacherDashboard();
  } finally {
    button.disabled = false;
    button.textContent = "Actualiser l’import";
  }
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "date inconnue";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function teacherSummary(records) {
  const count = records.length;
  const students = new Set(records.map((item) => `${item.class_name}|${item.last_name}|${item.first_name}`.toUpperCase())).size;
  const totalScore = records.reduce((sum, item) => sum + item.score, 0);
  const totalCoverage = records.reduce((sum, item) => sum + item.coverage, 0);
  return [
    ["Réponses", count, "ORAL ENREGISTRÉ"], ["Élèves", students, "IDENTITÉ UNIQUE"],
    ["Score moyen", count ? `${(totalScore / count).toFixed(2)} / 4` : "—", "BARÈME SVT"],
    ["Complétude", count ? `${Math.round(totalCoverage / count * 100)} %` : "—", "GRILLE ATTEINTE"],
    ["Réponses complètes", records.filter((item) => item.complete).length, "OBJECTIF ATTEINT"],
    ["Relectures", records.filter((item) => item.teacher_review_required || item.contradictory).length, "À VERIFIER"],
  ];
}

function filteredTeacherRecords(records) {
  const className = el("teacher-class-filter").value;
  const level = el("teacher-level-filter").value;
  const theme = el("teacher-theme-filter").value;
  return records.filter((item) => (!className || item.class_name === className) && (!level || `${item.level} · ${item.school_level}` === level) && (!theme || item.theme === theme));
}

function teacherFilterOptions(records) {
  for (const [id, values] of [
    ["teacher-class-filter", [...new Set(records.map((item) => item.class_name).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"))],
    ["teacher-level-filter", [...new Set(records.map((item) => `${item.level} · ${item.school_level}`).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"))],
    ["teacher-theme-filter", [...new Set(records.map((item) => item.theme).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"))],
  ]) {
    const select = el(id);
    const current = select.value;
    select.innerHTML = `<option value="">Tous</option>`;
    values.forEach((value) => { const option = document.createElement("option"); option.value = value; option.textContent = value; select.append(option); });
    select.value = values.includes(current) ? current : "";
  }
}

function resultDetail(record) {
  return `<details class="teacher-result-detail"><summary>Voir la réponse et la remédiation</summary><p><b>Transcription :</b> ${escapeHtml(record.transcription || "Non renseignée.")}</p><p><b>Remédiation :</b> ${escapeHtml(record.remediation || "Aucune remédiation enregistrée.")}</p>${record.missing_criteria?.length ? `<p><b>Manques :</b> ${escapeHtml(record.missing_criteria.join(" · "))}</p>` : ""}${record.misconceptions?.length ? `<p><b>Confusions :</b> ${escapeHtml(record.misconceptions.join(" · "))}</p>` : ""}</details>`;
}

function teacherTable(records) {
  if (!records.length) return `<div class="teacher-empty"><b>Aucun résultat pour ces filtres.</b><span>Modifie les filtres ou actualise l’import.</span></div>`;
  return `<div class="teacher-table-wrap"><table class="teacher-table"><thead><tr><th>Date</th><th>Élève</th><th>Classe</th><th>Question</th><th>Score</th><th>Couverture</th><th>Verdict</th><th>Détail</th></tr></thead><tbody>${records.slice(0, 150).map((item) => `<tr><td>${escapeHtml(formatDateTime(item.timestamp))}</td><td><b>${escapeHtml(`${item.first_name} ${item.last_name}`.trim() || "Sans nom")}</b><small>${escapeHtml(item.level)} · ${escapeHtml(item.school_level)}</small></td><td>${escapeHtml(item.class_name)}</td><td>${escapeHtml(item.title)}<small>${escapeHtml(item.theme)}</small></td><td><span class="score-chip">${escapeHtml(item.score)} / ${escapeHtml(item.max_score)}</span></td><td><div class="mini-bar"><i style="width:${percent(item.coverage)}"></i></div><small>${percent(item.coverage)}</small></td><td><span class="verdict ${item.contradictory ? "warning" : item.complete ? "good" : ""}">${escapeHtml(item.verdict)}</span></td><td>${resultDetail(item)}</td></tr>`).join("")}</tbody></table></div>`;
}

function statsTable(groups, title) {
  if (!groups?.length) return `<div class="teacher-stat-empty">Aucune donnée pour cette catégorie.</div>`;
  return `<div class="teacher-stat-card"><h3>${escapeHtml(title)}</h3>${groups.map((item) => `<div class="stat-row"><div class="stat-row-head"><b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.responses)} réponse${item.responses > 1 ? "s" : ""}</span></div><div class="stat-bars"><i class="score-bar" style="width:${percent(item.average_score / 4)}"></i><i class="coverage-bar" style="width:${percent(item.average_coverage)}"></i></div><small>Score ${escapeHtml(item.average_score.toFixed(2))} · couverture ${percent(item.average_coverage)} · complet ${percent(item.complete_rate)}</small></div>`).join("")}<div class="stat-legend"><span><i class="score-bar"></i> score moyen</span><span><i class="coverage-bar"></i> couverture</span></div></div>`;
}

function renderTeacherDashboard() {
  const data = state.teacherData;
  if (!data) return;
  const records = data.records || [];
  teacherFilterOptions(records);
  const filtered = filteredTeacherRecords(records);
  el("teacher-metrics").innerHTML = teacherSummary(filtered).map(([label, value, detail]) => `<div class="teacher-metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span><small>${escapeHtml(detail)}</small></div>`).join("");
  el("teacher-results-count").textContent = `${filtered.length} / ${records.length}`;
  el("teacher-results").innerHTML = teacherTable(filtered);
  const stats = data.stats || {};
  el("teacher-stats").innerHTML = statsTable(stats.by_class, "Par classe") + statsTable(stats.by_theme, "Par thème") + statsTable(stats.by_level, "Par cycle et niveau");
}

function showTeacherDashboard() {

  el("welcome-view").hidden = true;
  el("assessment-view").hidden = true;
  el("teacher-login-view").hidden = true;
  el("teacher-dashboard-view").hidden = false;
  document.body.classList.add("teacher-mode");
  el("student-chip").hidden = true;
  el("reset-button").hidden = true;
  setStep(0);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetSession() {
  if (state.mediaRecorder?.state === "recording") state.mediaRecorder.stop();
  stopStream();
  state.speechRecognition?.stop();
  state.speechRecognition = null;
  state.speechActive = false;
  clearAudio();
  state.selectedId = null;
  state.analysis = null;
  el("record-button").disabled = true;
  el("record-title").textContent = "Choisissez une question";
  el("record-help").textContent = "La réponse sera analysée sur cet appareil";
  el("transcript").value = "";
  el("transcript").disabled = true;
  el("audio-preview").hidden = true;
  el("focus-level").textContent = "";
  el("focus-theme").textContent = "";
  el("selected-title").textContent = "Choisissez une question";
  el("selected-context").textContent = "";
  el("selected-answer").textContent = "";
  showMessage("");
  updateTranscriptState();
  resetResult();
  renderQuestions();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function init() {
  try {
    const [catalog, health] = await Promise.all([api("/api/questions"), api("/api/health")]);
    state.questions = catalog.questions;
    state.hosted = Boolean(health.hosted);
    el("welcome-question-count").textContent = state.questions.length;
    populateFilters(catalog);
    renderQuestions();
    updateTranscriptState();
    if (state.hosted) {
      el("privacy-note").innerHTML = '<span class="pulse-dot"></span> Correction déterministe sur Vercel';
      el("hosted-audio-note").hidden = false;
      el("record-button").disabled = false;
      el("record-button").setAttribute("aria-label", "Démarrer la dictée");
      el("laya-toggle").checked = false;
      el("laya-toggle").disabled = true;
      el("laya-toggle").closest(".switch").title = "Laya est réservé à l’exécution locale";
    } else if (!health.whisper.installed) {
      toast("Whisper n’est pas installé : lancer install.ps1 avant la première transcription.");
    }
  } catch (error) {
    el("question-list").innerHTML = `<p class="source-note">Impossible de charger les questions : ${escapeHtml(error.message)}</p>`;
  }
}

el("level-filter").addEventListener("change", renderQuestions);
el("theme-filter").addEventListener("change", renderQuestions);
el("record-button").addEventListener("click", toggleRecording);
el("audio-file").addEventListener("change", handleUpload);
el("transcript").addEventListener("input", updateTranscriptState);
el("analyze-button").addEventListener("click", analyzeAnswer);
el("reset-button").addEventListener("click", resetSession);
el("edit-student-button").addEventListener("click", showWelcome);
el("teacher-entry-link").addEventListener("click", showTeacherLogin);
el("teacher-open-button").addEventListener("click", showTeacherLogin);
el("teacher-back-button").addEventListener("click", showWelcome);
el("teacher-dashboard-back-button").addEventListener("click", showWelcome);
el("teacher-login-form").addEventListener("submit", loginTeacher);
el("teacher-import-button").addEventListener("click", loadTeacherData);
el("teacher-logout-button").addEventListener("click", logoutTeacher);
el("teacher-class-filter").addEventListener("change", () => state.teacherData && renderTeacherDashboard());
el("teacher-level-filter").addEventListener("change", () => state.teacherData && renderTeacherDashboard());
el("teacher-theme-filter").addEventListener("change", () => state.teacherData && renderTeacherDashboard());
el("student-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!validateIdentity()) return;
  state.student = {
    last_name: el("student-last-name").value,
    first_name: el("student-first-name").value,
    class_name: el("student-class").value,
  };
  resetIdentityForm();
  showAssessment();
});
window.addEventListener("beforeunload", () => {
  if (state.mediaRecorder?.state === "recording") state.mediaRecorder.stop();
  stopStream();
  state.speechRecognition?.stop();
  state.speechRecognition = null;
  state.speechActive = false;
  clearAudio();
});
init();



