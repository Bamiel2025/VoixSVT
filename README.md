# Voix SVT — Correcteur audio de réponses SVT

Application web de correction de réponses orales courtes de SVT (cycles 3 et 4). Deux modes sont prévus :

- **local** : transcription Faster‑Whisper et complément Laya‑MLX sur le poste ;
- **Vercel** : grille déterministe, dictée du navigateur lorsqu’elle est disponible et import/export Google Sheets côté serveur.

L’identité et le résultat sont exportables vers Google Sheets via une Web App Apps Script configurée par l’enseignant. L’espace enseignant est protégé côté serveur par un code et une session signée.

## Démarrage rapide

```powershell
cd D:\IA\CorrecteurAuto
.\install.ps1
.\start.ps1
```

Ouvrir ensuite [http://127.0.0.1:8765](http://127.0.0.1:8765).

## Parcours d’utilisation

1. Saisir le nom, le prénom et la classe sur la page d’accueil.
2. Filtrer et choisir une question.
3. Enregistrer une réponse de 10 à 30 secondes, importer un audio, ou saisir directement la transcription.
4. Vérifier/corriger la transcription.
5. Lancer l’analyse. La grille déterministe est immédiate ; Laya est calculé ensuite en arrière-plan.
6. Lire les éléments trouvés, les manques, l’indice Laya et l’activité de remédiation. Si Google Sheets est configuré, le statut d’export apparaît dans le diagnostic.

7. Cliquer sur **Espace enseignant**, saisir le code défini dans `TEACHER_ACCESS_CODE`, puis importer le registre Google Sheets.
8. Filtrer par classe, cycle/niveau ou thème et consulter le registre, les réponses détaillées et les statistiques.

## Espace enseignant

- Le code n’est jamais inscrit dans le HTML, le JavaScript ou Git : il est lu dans la variable serveur `TEACHER_ACCESS_CODE`.
- Une tentative réussie crée un cookie `HttpOnly`, `SameSite=Strict`, signé par `TEACHER_SESSION_SECRET`, valable huit heures.
- Toutes les routes d’import et les résultats sont revérifiés côté serveur ; le JavaScript public ne reçoit les données qu’après validation.
- Sans `GOOGLE_SHEETS_APP_URL`, la connexion reste protégée mais l’import affiche une configuration manquante.
- La clé secrète de la Web App Apps Script ne doit jamais être communiquée aux élèves. Elle est conservée uniquement dans les variables Vercel.

## Ce que fait le moteur

- **Grille déterministe** : normalisation des accents, groupes de synonymes, expressions attendues, pondération et détection de formulations niées.
- **Laya décisionnel** : deux têtes `noul` évaluent la justesse et la complétude. Elles ne génèrent ni texte ni note et ne remplacent jamais la grille.
- **Whisper local** : modèle français CPU, audio temporaire supprimé après transcription.
- **Confidentialité locale** : serveur limité à `127.0.0.1`, transcription et diagnostic sur le poste, CSP et en-têtes de protection, analyses conservées seulement en mémoire.
- **Confidentialité hébergée** : aucune transcription Whisper ni inférence Laya n’est chargée sur Vercel. La Web Speech API peut dépendre du navigateur ; la transcription reste modifiable avant analyse. L’export Google Sheets reste facultatif.

> **Usage pédagogique** : vérifier toujours la transcription avant l’analyse. Une transcription vocale, une formulation orale inhabituelle ou une confidence Laya faible imposent une relecture humaine.

## Banque de questions

La banque contient **87 questions** : 78 prompts oraux issus de 2 questions de synthèse dans chacun des 39 quiz de `D:\IA\Wooflashquizz\index.html`, complétés par 9 grilles pédagogiques curationnées. Les niveaux d’origine sont conservés et le filtre va de la 6e à la 3e. Les erreurs historiques de classement sont corrigées : passage des nutriments et enzymes en 5e/cycle 4, vent en 4e/cycle 4, reproduction asexuée conservée en 5e/cycle 3.

Les 9 grilles complémentaires proviennent de :

- `D:\IA\Alimentation.html`
- `D:\IA\vent2.html`
- `D:\IA\Asexuesexue.html`
- `D:\IA\nutrition des plantes.html`
- `D:\IA\Activite_Nossal_Cycle4.html`
- `D:\IA\vaccinationfinal.html`
- `D:\IA\SNVXglm.html`
- `D:\IA\biodiversite2.html`

Chaque entrée contient une réponse de référence, une ou plusieurs misconceptions et une remédiation. Pour ajouter une question, copiez un fichier de banque et ajoutez un objet respectant le même schéma dans `questions`.

## Export Google Sheets et statistiques

Le script prêt à coller dans Apps Script se trouve dans `D:\IA\CorrecteurAuto\apps-script\Code.gs`. Il crée deux onglets : `Résultats` (une ligne par oral) et `Statistiques` (synthèse par classe, thème et cycle). Le script refuse les données incomplètes, échappe les valeurs et déduplique les envois par identifiant d’analyse.

1. Ouvrir <https://script.google.com>, créer un projet et coller `apps-script\Code.gs`.
2. Exécuter une fois `initialiser()` et autoriser Google Sheets, puis publier via **Déployer → Nouveau déploiement → Application Web**.
3. Choisir **Exécuter en tant que : Moi** et un accès permettant les requêtes anonymes (« Toute personne », ou « Toute personne innerhalb de votre organisation »). Le client Python n’utilise pas le compte Google de l’élève.
4. Pour protéger les résultats, ajouter dans **Propriétés du script → Script Properties** `WEB_APP_SECRET` avec une valeur aléatoire d’au moins 32 caractères, puis copier l’URL `/exec?key=VOTRE_CLE`.
5. Démarrer l’application dans la même session PowerShell :

```powershell
$env:GOOGLE_SHEETS_APP_URL = 'https://script.google.com/macros/s/IDENTIFIANT/exec?key=VOTRE_CLE'
.\start.ps1
```

Si votre organisation Google Workspace interdit l’accès anonyme, cette intégration par URL `/exec` ne peut pas être appelée telle quelle : il faudra lui ajouter un proxy authentifié plutôt que d’exposer la Web App.

Le statut d’export est visible dans le diagnostic. Si Laya est activé, l’envoi attend la fin de son calcul afin que le tableau contienne l’état décisionnel final.

## Déploiement GitHub et Vercel

Le dépôt est configuré pour un runtime Python FastAPI via `api/index.py` et `vercel.json`.

1. Pousser la branche contenant ce projet vers `https://github.com/Bamiel2025/VoixSVT.git`.
2. Dans Vercel, importer ce dépôt avec le preset **Other** ; Vercel détecte Python et `api/index.py`.
3. Ajouter dans **Settings → Environment Variables** les variables de production :
   - `TEACHER_ACCESS_CODE` : le code choisi par l’enseignant ;
   - `TEACHER_SESSION_SECRET` : secret aléatoire d’au moins 32 caractères ;
   - `GOOGLE_SHEETS_APP_URL` : URL `/exec?key=...` de la Web App ;
   - `COOKIE_SECURE=1` ;
   - `GOOGLE_SHEETS_TIMEOUT=10`.
4. Déployer. Les URL `/api/...` et les fichiers statiques sont redirigés vers la fonction FastAPI.

> En mode Vercel, les élèves utilisent la dictée du navigateur lorsqu’elle est disponible, ou saisissent la transcription. Whisper, l’import de fichiers audio et Laya restent des fonctions de l’exécution locale.

## Configuration locale

Variables facultatives :

```powershell
$env:WHISPER_MODEL = 'small'       # tiny, base, small, medium...
$env:LAYA_PYTHON = 'D:\IA\laramxl\laya-mlx\.venv\Scripts\python.exe'
$env:LAYA_WORKER = 'D:\IA\laramxl\mcp-laya\worker.py'
$env:MAX_AUDIO_SECONDS = '45'
```

Le premier lancement de Whisper peut télécharger le modèle `small`. Ce téléchargement porte uniquement sur les poids du modèle ; l’inférence reste locale. Laya est déjà installé et son checkpoint multilingue est présent dans `D:\IA\laramxl`.

## Développement et tests

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m app.main
```

## Structure

- `app/main.py` : API FastAPI, session enseignant, transcription locale, analyse Laya et export Sheets.
- `app/grader.py` : moteur de grille déterministe.
- `app/laya_client.py` : worker JSON-lines Laya persistant.
- `app/sheets_client.py` : contrat Python → Google Apps Script.
- `app/transcription.py` : intégration Faster‑Whisper.
- `app/data/` : questions et grilles SVT.
- `app/static/` : interface sans dépendance graphique distante.
- `apps-script/Code.gs` : dépôt Google Sheets et tableaux de statistiques.
- `tests/` : tests de correction, frontend statique et API.
