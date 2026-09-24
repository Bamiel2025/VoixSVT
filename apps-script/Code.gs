/**
 * Voix SVT — dépôt des oraux et statistiques Google Sheets.
 *
 * Déploiement :
 * 1. Coller ce fichier dans un projet Apps Script et exécuter initialiser().
 * 2. Déployer > Nouveau déploiement > Application Web.
 * 3. Exécuter en tant que Moi ; autoriser les appels anonymes requis par le client Python.
 * 4. Définir WEB_APP_SECRET dans Script Properties, puis copier l'URL /exec?key=... dans GOOGLE_SHEETS_APP_URL.
 *
 * Secret facultatif :
 * - Propriétés du script > Script Properties > WEB_APP_SECRET = valeur secrète.
 * - Utiliser ensuite une URL /exec?key=LONGUE_VALEUR.
 */

var APP = {
  name: 'Voix SVT — Résultats',
  resultsSheet: 'Résultats',
  statsSheet: 'Statistiques',
  schema: 'voix-svt-analysis-v1',
  spreadsheetProperty: 'VOIX_SVT_SPREADSHEET_ID'
};

// Laisser vide pour utiliser la feuille liée, puis créer une feuille sinon.
var SPREADSHEET_ID = '';

var RESULT_HEADERS = [
  'Horodatage', 'Identifiant analyse', 'Prénom', 'Nom', 'Classe',
  'Cycle', 'Niveau', 'Thème', 'Question', 'ID question', 'Transcription',
  'Score', 'Maximum', 'Verdict', 'Couverture', 'Complète', 'Contradiction',
  'Critères trouvés', 'Critères manquants', 'Confusions', 'Remédiation',
  'Laya — statut', 'Laya — décision', 'Laya — concordance',
  'Relecture enseignant', 'Source'
];

function doGet(e) {
  try {
    assertAuthorized_(e);
    var action = e && e.parameter && e.parameter.action ? e.parameter.action : 'status';
    if (action === 'stats') {
      var records = readRecords_(getSheet_(getSpreadsheet_(), APP.resultsSheet));
      return json_({ ok: true, stats: computeStats_(records) });
    }
    if (action === 'dashboard') {
      var records = readRecords_(getSheet_(getSpreadsheet_(), APP.resultsSheet));
      return json_({ ok: true, records: records, stats: computeStats_(records) });
    }
    return json_({
      ok: true,
      service: 'Voix SVT',
      configured: Boolean(getSpreadsheetId_()),
      message: 'Web App opérationnelle. Utilisez POST pour ajouter un oral.'
    });
  } catch (error) {
    return json_({ ok: false, error: errorMessage_(error) });
  }
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  var locked = false;
  try {
    lock.waitLock(30000);
    locked = true;
    assertAuthorized_(e);
    if (!e || !e.postData || !e.postData.contents) {
      throw new Error('Corps POST JSON absent.');
    }
    if (e.postData.contents.length > 50000) {
      throw new Error('Payload trop volumineux.');
    }
    var payload = validatePayload_(JSON.parse(e.postData.contents));
    var spreadsheet = getSpreadsheet_();
    var sheet = initializeSheets_(spreadsheet);
    var result = upsertResult_(sheet, payload);
    writeStatistics_(getSheet_(spreadsheet, APP.statsSheet));
    SpreadsheetApp.flush();
    return json_({
      ok: true,
      message: result.created ? 'Résultat ajouté.' : 'Résultat déjà présent : ligne actualisée.',
      action: result.created ? 'created' : 'updated'
    });
  } catch (error) {
    return json_({ ok: false, error: errorMessage_(error) });
  } finally {
    if (locked) lock.releaseLock();
  }
}

/** Exécutez cette fonction une fois avant le premier déploiement. */
function initialiser() {
  var spreadsheet = getSpreadsheet_();
  initializeSheets_(spreadsheet);
  writeStatistics_(getSheet_(spreadsheet, APP.statsSheet));
  Logger.log('Voix SVT initialisé : %s', spreadsheet.getUrl());
  return spreadsheet.getUrl();
}

function getSpreadsheetId_() {
  var properties = PropertiesService.getScriptProperties();
  return SPREADSHEET_ID || properties.getProperty(APP.spreadsheetProperty) || '';
}

function getSpreadsheet_() {
  var id = getSpreadsheetId_();
  if (id) return SpreadsheetApp.openById(id);
  var active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) {
    PropertiesService.getScriptProperties().setProperty(APP.spreadsheetProperty, active.getId());
    return active;
  }
  var created = SpreadsheetApp.create(APP.name);
  PropertiesService.getScriptProperties().setProperty(APP.spreadsheetProperty, created.getId());
  return created;
}
function getSheet_(spreadsheet, name) {
  var sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
    if (name === APP.resultsSheet) {
      sheet.getRange(1, 1, 1, RESULT_HEADERS.length).setValues([RESULT_HEADERS]);
      sheet.getRange(1, 1, 1, RESULT_HEADERS.length)
        .setBackground('#18352e').setFontColor('#ffffff').setFontWeight('bold')
        .setHorizontalAlignment('center').setVerticalAlignment('middle');
      sheet.setFrozenRows(1);
      sheet.setTabColor('#176b55');
      sheet.getRange('A2:A').setNumberFormat('dd/mm/yyyy hh:mm:ss');
      sheet.getRange('O2:O').setNumberFormat('0%');
      sheet.getRange('D:D').setNumberFormat('@');
      var widths = [150, 180, 100, 120, 80, 80, 70, 180, 320, 140, 360, 65, 70, 130, 90, 75, 90, 260, 260, 260, 240, 100, 170, 130, 110, 240];
      for (var i = 0; i < widths.length; i++) sheet.setColumnWidth(i + 1, widths[i]);
      if (sheet.getFilter() == null) {
        sheet.getRange(1, 1, Math.max(sheet.getMaxRows(), 2), RESULT_HEADERS.length).createFilter();
      }
    }
  }
  return sheet;
}

function initializeSheets_(spreadsheet) {
  var results = getSheet_(spreadsheet, APP.resultsSheet);
  getSheet_(spreadsheet, APP.statsSheet);
  return results;
}

function assertAuthorized_(event) {
  var secret = PropertiesService.getScriptProperties().getProperty('WEB_APP_SECRET') || '';
  if (!secret) throw new Error('WEB_APP_SECRET absent : configurez-le avant de publier la Web App.');
  var supplied = event && event.parameter && event.parameter.key ? String(event.parameter.key) : '';
  if (supplied !== secret) throw new Error('Clé d’accès invalide.');
}

function validatePayload_(data) {
  if (!data || data.schema !== APP.schema) throw new Error('Schéma de données non reconnu.');
  var required = [
    ['analysis_id', 100], ['created_at', 50],
    ['student.first_name', 80], ['student.last_name', 80], ['student.class_name', 40],
    ['question.id', 120], ['question.level', 30], ['question.school_level', 20],
    ['question.theme', 160], ['question.title', 220], ['question.prompt', 1000],
    ['transcription', 1200], ['result.label', 160], ['result.verdict', 80]
  ];
  for (var i = 0; i < required.length; i++) {
    var value = nestedValue_(data, required[i][0]);
    if (value === '' || value == null) throw new Error('Champ obligatoire manquant : ' + required[i][0]);
    if (String(value).length > required[i][1]) throw new Error('Champ trop long : ' + required[i][0]);
  }
  var score = Number(nestedValue_(data, 'result.score'));
  var maximum = Number(nestedValue_(data, 'result.max_score'));
  var coverage = Number(nestedValue_(data, 'result.coverage'));
  if (!isFinite(score) || score < 0 || score > 4) throw new Error('Score invalide.');
  if (!isFinite(maximum) || maximum !== 4) throw new Error('Barème invalide.');
  if (!isFinite(coverage) || coverage < 0 || coverage > 1) throw new Error('Couverture invalide.');
  if (isNaN(new Date(data.created_at).getTime())) throw new Error('Date invalide.');
  return data;
}

function nestedValue_(object, path) {
  return path.split('.').reduce(function(value, key) {
    return value == null ? '' : value[key];
  }, object);
}

function upsertResult_(sheet, data) {
  var id = String(data.analysis_id);
  var lastRow = Math.max(sheet.getLastRow(), 1);
  var ids = lastRow > 1 ? sheet.getRange(2, 2, lastRow - 1, 1).getValues() : [];
  var rowIndex = 0;
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === id) {
      rowIndex = i + 2;
      break;
    }
  }
  var result = data.result || {};
  var row = [
    new Date(data.created_at), safeCell_(id),
    safeCell_(data.student.first_name), safeCell_(data.student.last_name), safeCell_(data.student.class_name),
    safeCell_(data.question.level), safeCell_(data.question.school_level), safeCell_(data.question.theme),
    safeCell_(data.question.title), safeCell_(data.question.id), safeCell_(data.transcription),
    Number(result.score), Number(result.max_score), safeCell_(result.label), safeCell_(result.verdict),
    Number(result.coverage), result.complete ? 'Oui' : 'Non', result.contradictory ? 'Oui' : 'Non',
    safeCell_(joinList_(data.matched_criteria)), safeCell_(joinList_(data.missing_criteria)),
    safeCell_(joinList_(data.misconceptions)), safeCell_((data.remediation || {}).title || ''),
    safeCell_(((data.laya || {}).status) || 'inconnu'), safeCell_(((data.laya || {}).decision_label) || ''),
    safeCell_(((data.laya || {}).agreement) || ''), result.teacher_review_required ? 'Oui' : 'Non',
    safeCell_(((data.source || {}).file) || '') + ' · ' + (((data.source || {}).locator) || '')
  ];
  if (rowIndex) {
    sheet.getRange(rowIndex, 1, 1, RESULT_HEADERS.length).setValues([row]);
    return { created: false, row: rowIndex };
  }
  sheet.appendRow(row);
  return { created: true, row: sheet.getLastRow() };
}

function safeCell_(value) {
  var text = value == null ? '' : String(value);
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function joinList_(values) {
  return Array.isArray(values) ? values.join(' · ') : '';
}

function splitList_(value) {
  var text = String(value || '').trim();
  return text ? text.split(/\s+·\s+/).filter(function(item) { return item; }) : [];
}

function readRecords_(sheet) {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  var values = sheet.getRange(2, 1, lastRow - 1, RESULT_HEADERS.length).getValues();
  var records = [];
  for (var i = 0; i < values.length; i++) {
    var row = values[i];
    if (!String(row[1])) continue;
    records.push({
      timestamp: row[0], analysisId: String(row[1]),
      firstName: String(row[2] || ''), lastName: String(row[3] || ''), className: String(row[4] || ''),
      level: String(row[5] || ''), schoolLevel: String(row[6] || ''), theme: String(row[7] || ''),
      title: String(row[8] || ''), questionId: String(row[9] || ''),
      transcription: String(row[10] || ''),
      score: Number(row[11]) || 0, maxScore: Number(row[12]) || 4,
      label: String(row[13] || ''), verdict: String(row[13] || ''),
      coverage: Number(row[14]) || 0,
      complete: String(row[15]) === 'Oui', contradictory: String(row[16]) === 'Oui',
      matchedCriteria: splitList_(row[17]), missingCriteria: splitList_(row[18]),
      misconceptions: splitList_(row[19]), remediation: String(row[20] || ''),
      review: String(row[24]) === 'Oui'
    });
  }
  return records;
}

function computeStats_(records) {
  var byClass = aggregateStats_(records, function(row) { return row.className || 'Non renseignée'; });
  var byTheme = aggregateStats_(records, function(row) { return row.theme || 'Non renseigné'; });
  var byLevel = aggregateStats_(records, function(row) { return row.level + ' · ' + row.schoolLevel; });
  var students = {};
  records.forEach(function(row) {
    students[(row.className + '|' + row.lastName + '|' + row.firstName).toUpperCase()] = true;
  });
  var totalScore = records.reduce(function(sum, row) { return sum + row.score; }, 0);
  var totalCoverage = records.reduce(function(sum, row) { return sum + row.coverage; }, 0);
  return {
    generatedAt: new Date().toISOString(), totalResponses: records.length,
    uniqueStudents: Object.keys(students).length,
    averageScore: records.length ? round_(totalScore / records.length) : 0,
    averageCoverage: records.length ? round_(totalCoverage / records.length) : 0,
    completeResponses: records.filter(function(row) { return row.complete; }).length,
    misconceptions: records.filter(function(row) { return row.contradictory; }).length,
    reviews: records.filter(function(row) { return row.review; }).length,
    byClass: byClass, byTheme: byTheme, byLevel: byLevel
  };
}

function aggregateStats_(records, keyFunction) {
  var groups = {};
  records.forEach(function(row) {
    var key = keyFunction(row);
    if (!groups[key]) groups[key] = { label: key, responses: 0, score: 0, coverage: 0, complete: 0, reviews: 0 };
    groups[key].responses++;
    groups[key].score += row.score;
    groups[key].coverage += row.coverage;
    if (row.complete) groups[key].complete++;
    if (row.review) groups[key].reviews++;
  });
  return Object.keys(groups).sort().map(function(key) {
    var group = groups[key];
    return {
      label: group.label, responses: group.responses,
      averageScore: round_(group.score / group.responses),
      averageCoverage: round_(group.coverage / group.responses),
      completeRate: round_(group.complete / group.responses), reviews: group.reviews
    };
  });
}

function writeStatistics_(sheet) {
  var resultsSheet = sheet.getParent().getSheetByName(APP.resultsSheet);
  var stats = computeStats_(readRecords_(resultsSheet));
  var rows = [
    ['Voix SVT — tableau de bord', '', '', '', '', ''],
    ['Mise à jour', new Date(), '', '', '', ''], ['', '', '', '', '', ''],
    ['Indicateur global', 'Valeur', '', '', '', ''],
    ['Réponses enregistrées', stats.totalResponses, '', '', '', ''],
    ['Élèves uniques', stats.uniqueStudents, '', '', '', ''],
    ['Score moyen / 4', stats.averageScore, '', '', '', ''],
    ['Couverture moyenne', stats.averageCoverage, '', '', '', ''],
    ['Réponses complètes', stats.completeResponses, '', '', '', ''],
    ['Confusions détectées', stats.misconceptions, '', '', '', ''],
    ['Relectures suggérées', stats.reviews, '', '', '', ''], ['', '', '', '', '', '']
  ];
  appendStatsTable_(rows, 'Par classe', stats.byClass);
  appendStatsTable_(rows, 'Par thème', stats.byTheme);
  appendStatsTable_(rows, 'Par cycle et niveau', stats.byLevel);
  sheet.clear();
  sheet.getRange(1, 1, rows.length, 6).setValues(rows);
  sheet.setFrozenRows(3);
  sheet.setTabColor('#ddeb73');
  sheet.getRange(1, 1, 1, 6).merge().setBackground('#18352e').setFontColor('#ffffff').setFontSize(16).setFontWeight('bold');
  sheet.getRange(2, 1, 1, 2).merge();
  sheet.getRange(2, 2).setNumberFormat('dd/mm/yyyy hh:mm:ss').setHorizontalAlignment('left');
  styleStats_(sheet, rows);
  sheet.getRange('A:A').setWidth(240);
  sheet.getRange('B:F').setWidth(130);
  sheet.setHiddenGridlines(true);
}

function appendStatsTable_(rows, title, data) {
  rows.push([title, '', '', '', '', '']);
  rows.push(['Catégorie', 'Réponses', 'Score / 4', 'Couverture', 'Taux complet', 'Relectures']);
  data.forEach(function(item) {
    rows.push([item.label, item.responses, item.averageScore, item.averageCoverage, item.completeRate, item.reviews]);
  });
  rows.push(['', '', '', '', '', '']);
}

function styleStats_(sheet, rows) {
  for (var i = 0; i < rows.length; i++) {
    var label = String(rows[i][0] || '');
    if (label === 'Indicateur global') {
      sheet.getRange(i + 1, 1, 1, 6).setBackground('#dff1e7').setFontWeight('bold');
    }
    if (label === 'Par classe' || label === 'Par thème' || label === 'Par cycle et niveau') {
      sheet.getRange(i + 1, 1, 1, 6).merge().setBackground('#176b55').setFontColor('#ffffff').setFontSize(13).setFontWeight('bold');
    }
    if (label === 'Catégorie') {
      sheet.getRange(i + 1, 1, 1, 6).setBackground('#eee8da').setFontWeight('bold');
    }
  }
  sheet.getRange(1, 1, rows.length, 6).setVerticalAlignment('middle');
  sheet.getRange(7, 2).setNumberFormat('0.00');
  sheet.getRange(8, 2).setNumberFormat('0%');
  for (var j = 0; j < rows.length; j++) {
    if (String(rows[j][0] || '') === 'Catégorie') {
      var first = j + 2;
      if (rows.length > first) {
        sheet.getRange(first, 4, rows.length - first + 1, 2).setNumberFormat('0%');
      }
    }
  }
}

function round_(value) {
  return Math.round(Number(value) * 100) / 100;
}

function json_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function errorMessage_(error) {
  return error && error.message ? error.message : String(error);
}
