# Clair — analyse documentaire IA locale

Chargez un PDF, DOCX ou TXT, posez vos questions en français et consultez les passages sources. Pour les questions et les résumés, Clair propose **WebNN**, **llama.cpp sur CPU** et **Wllama sur CPU dans Edge**. Le choix **Automatique** utilise **Qwen3 4B WebNN** s'il est installé. Le serveur local extrait le texte, choisit les passages et vérifie les références. Aucun document ni question n'est transmis à une API cloud.

**Pour expliquer l'application :** lire [Comprendre le fonctionnement](docs/FONCTIONNEMENT.md), avec un schéma, les deux modes de résumé et une explication à reprendre à l'oral. L'[index de la documentation](docs/README.md) distingue les guides actuels des anciens rapports et captures. Documentation relue le 18 novembre 2026.

Les essais dans Edge sont décrits dans [la validation](docs/VALIDATION.md).

## Démarrer sous Windows

1. Au premier lancement ou après cette mise à jour, double-cliquez sur **`installer.bat`**. Le modèle WebNN nécessite environ 566 Mo de téléchargement.
2. Double-cliquez sur **`demarrer.bat`**. Clair s'ouvre dans un profil Edge dédié où WebNN est activé.
3. Cliquez sur **Ouvrir le document de démonstration**, ou importez votre fichier.
4. Posez par exemple : **« Quel est le budget annoncé pour 2027 ? »**
5. Cliquez sur une carte source sous la réponse pour vérifier son contenu.

Internet sert à l'installation des dépendances et du modèle. Les lancements suivants utilisent les fichiers locaux. Si une ancienne version du serveur tourne, lancez `arreter.bat` avant `demarrer.bat`.

Après récupération d'une nouvelle version des sources, relancez `installer.bat` pour mettre à jour les dépendances et reconstruire l'interface. Le lanceur vérifie la présence de l'environnement et de l'interface construite ; il ne détecte pas toutes les dépendances nouvelles d'une mise à jour.

Prérequis pour une nouvelle machine : Windows 11, Edge, Python 3.11+ et Node.js 20.19+. La première réponse inclut le chargement du modèle dans Edge.

**Choisir le matériel pour le chat, les résumés et la traduction.** Dans les paramètres, choisissez le modèle puis **Calcul WebNN**. **Automatique** essaie NPU → GPU → CPU. **GPU prioritaire** essaie GPU → NPU → CPU ; **NPU prioritaire** essaie NPU → GPU → CPU. **CPU uniquement** ne teste aucun accélérateur. Un seul contexte est retenu par appel : les puissances du GPU et du NPU ne sont pas additionnées. Le réglage est conservé sur ce navigateur.

Chaque accélérateur doit réussir un test de génération avec le modèle avant utilisation. Un périphérique peut être présent mais incompatible avec ce modèle ou ses pilotes ; Clair essaie alors le suivant. Le bandeau **Dernier calcul WebNN** indique le contexte ayant terminé la génération, avec le détail des échecs et des replis. Il ne certifie pas l'identité physique de la puce ni l'affectation de toutes les opérations ; certaines peuvent rester sur CPU. Les échecs sont mémorisés par modèle et contexte dans l'onglet pour ne pas répéter les compilations à chaque bloc. **Retester GPU / NPU au prochain calcul** permet de réessayer, notamment après une mise à jour de pilote. La première réponse inclut le chargement du modèle.

Pour ajouter **Qwen3 4B** sur un autre poste, exécutez `.\scripts\installer-webnn.ps1 -Model qwen3-4b` depuis PowerShell après `installer.bat`, puis rechargez Clair. Prévoyez environ 2,5 Go de téléchargement et 8 Go d'espace pour le téléchargement, la préparation et les fichiers qui seront servis à Edge. La commande `.\scripts\installer-webnn.ps1 -Model qwen25-15b` installe **Qwen2.5 1,5B Instruct** (1,36 Go).

## Utilisation

### Choisir llama.cpp pour les questions et les résumés

Dans **Paramètres du modèle → Modèle local**, sélectionnez **Qwen3 4B · llama.cpp (CPU)**. Les réponses affichent le moteur utilisé et les passages sources. Clair démarre le moteur à la première génération de la demande et le libère à la fin ou à l'arrêt. Les préparations et résumés réutilisent le processus entre leurs lots.

Sur un autre poste Windows x64, installez le binaire et le GGUF par cette commande PowerShell depuis la racine de Clair, puis rechargez la page. Le premier téléchargement représente environ 2,5 Go.

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_cpu --install-only
```

### Choisir Wllama dans Edge

Dans **Paramètres du modèle → Modèle local**, sélectionnez **Qwen3 4B · Wllama (CPU)** depuis un profil Edge normal. Edge utilise le GGUF de Clair via WebAssembly. La première demande remplit le cache du navigateur à partir du fichier servi sur `localhost`. Prévoyez environ 2,5 Go de stockage supplémentaires pour ce cache.

Si le GGUF est absent, installez uniquement les poids depuis la racine du projet, puis rechargez Clair.

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_cpu --install-gguf
```

### Traduire un document

Après importation, cliquez sur **Traduire**, choisissez le moteur et la langue puis cliquez sur **Traduire le document**.

- **WebNN** utilise le modèle et le réglage matériel des paramètres. Il détecte la langue d'origine et propose l'anglais, le français, l'espagnol, l'allemand, l'italien, le portugais et le néerlandais comme langues cibles.
- **Bergamot (CPU)** traduit le français et l'anglais dans les deux sens. Sous Windows x64, double-cliquez une fois sur **`installer-traduction.bat`**, puis rechargez Clair. Dans **Traduire**, sélectionnez **Bergamot (CPU)** et indiquez le sens de traduction. L'installation télécharge le binaire [translateLocally](https://github.com/XapaJIaMnu/translateLocally) et les deux modèles. Les traductions s'effectuent ensuite hors ligne.

Clair parcourt **tout le texte extrait**, dans l'ordre des pages ou des blocs, sans utiliser les résumés ni la recherche de passages. La progression indique les blocs terminés. **Arrêter la traduction** conserve ces blocs ; relancer avec la même langue et le même modèle reprend le travail manquant, y compris après redémarrage. Vous pouvez changer de préférence matérielle à la reprise : les anciens blocs sont conservés et leurs contextes de calcul sont indiqués séparément. Une réponse tronquée est redécoupée en passages plus courts ; si le modèle n'aboutit pas, l'erreur est affichée et l'export complet reste indisponible.

Une fois la traduction terminée, cliquez sur **Télécharger la traduction en DOCX**. Le fichier conserve des repères de pages ou de blocs sources et les titres reconnaissables. Il ne reproduit pas la mise en page originale, les images ou les tableaux complexes. Les pages scannées nécessitent un OCR avant importation ; les avertissements d'extraction accompagnent le résultat. La traduction automatique doit être relue : le parcours de tous les blocs ne prouve pas la fidélité de chaque phrase. Les langues proposées demandent une validation adaptée aux documents utilisés.

Avec WebNN, la traduction utilise un contexte réduit de 1 024 tokens. Chaque moteur libère ses ressources à la fin de la traduction ou à l'arrêt. Le chat et les préparations WebNN les libèrent après 30 secondes sans nouvelle demande. Les mesures et leurs limites sont décrites dans [la validation](docs/VALIDATION.md).

### Questions et résumés

- Importation PDF, DOCX, TXT encodé UTF-8, limite par défaut 100 Mo. Scans : avertissement, OCR à ajouter.
- Résumé, points importants, risques et décisions par les boutons rapides.
- Paramètres en haut à droite : modèle installé et stratégie automatique, résumé rapide, lecture directe, résumé approfondi, résumé + BM25 ou recherche BM25. Les demandes de résumé en mode automatique utilisent désormais le mode rapide.
- **Résumé rapide** réutilise le texte extrait, sélectionne des phrases dans les sections et sur toute la longueur du document, puis effectue un seul appel de rédaction. Les pages de sommaire détectées sont exclues de cette sélection. La liste des sections retenues et omises est affichée sous le résumé ; une section retenue peut encore perdre des détails. Si tout le texte tient dans le contexte, il est fourni intégralement.
- Si WebNN renvoie un résumé rapide incomplet ou des citations invalides, Clair affiche des **extraits clés** des pages retenues, avec leurs sources. Cette réponse est identifiée dans la conversation et ne remplace pas un résumé généré dans le cache.
- **Résumé approfondi** lit tous les blocs extraits avec une hiérarchie dont les lots sont calculés en tokens. Les résultats intermédiaires compatibles sont réutilisés, y compris les anciens lots reconnus ; le contenu des passages et les paramètres du modèle entrent dans les clés des nouveaux caches. Ni le mode rapide ni le mode approfondi ne lisent les images ou n'ajoutent d'OCR.
- Formats : réponse courte, détaillée, résumé structuré, points clés.
- Les consignes envoyées au modèle sont compactées : règles répétées et seconde liste des sources supprimées, séparateurs vides réduits. Les extraits strictement identiques avec le même titre sont regroupés pour les questions, en conservant leurs références. Les nombres, négations, tableaux et indentations du texte source sont préservés.
- **Réponse courte** réserve 256 tokens ; **Points clés**, 384 ; les formats détaillés, 640. Pour les résumés structurés des modes rapide, approfondi et hybride, les consignes visent respectivement 70, 100 ou 150 mots selon ce plafond. Pour les autres réponses, les points clés visent 120 mots et les formats longs 200. Ce sont des consignes au modèle, pas des longueurs garanties.
- Une question strictement identique, avec le même document, modèle, stratégie et format, réutilise sa réponse terminée et ses sources. La mention **réponse réutilisée** l'indique. Ce cache n'est pas une nouvelle vérification par le modèle ; les réponses sans citation, aux citations invalides ou tronquées en sont exclues. Un changement de paramètres ou de poids du modèle invalide la réutilisation.
- **Préparer les synthèses** lance les lots locaux ; leur progression apparaît à gauche. **Interrompre la préparation** conserve les lots terminés. Relancer reprend le calcul manquant, même après fermeture du serveur.
- Une préparation complète peut prendre du temps sur CPU. Une question factuelle utilise d'abord la recherche textuelle ; préparer tout le document n'est pas obligatoire.
- Pendant un résumé complet, la conversation affiche les lots terminés sur le total de l'étape, les lots réutilisés et le temps écoulé. Le total change lors des regroupements ; il ne représente pas un pourcentage global. Le bouton carré interrompt aussi la préparation déclenchée par la question. Les lots terminés sont conservés.
- Les petites sections sont regroupées dans le même lot quand le contexte le permet. Les anciennes synthèses compatibles sont réutilisées.
- La préparation approfondie utilise le contexte du modèle sélectionné. Un lot intermédiaire ou racine tronqué peut être retenté une fois avec une consigne plus concise. Une réponse finale structurée tronquée est rejetée et exclue du cache.
- Une synthèse globale terminée est retrouvée directement aux préparations suivantes. Les anciens lots restent disponibles ; leur premier parcours complet crée ce raccourci sans recalcul des lots compatibles.
- Chaque question est autonome : mentionnez son sujet dans les relances. L'historique est conservé par document.
- **Mesures techniques** en bas : temps, tokens, appels et RAM observée. Les tokens, durées natives et chargements de tous les appels (y compris les tentatives tronquées) sont cumulés ; le détail par appel est conservé dans `llm_calls` dans SQLite. Les avertissements sous chaque réponse indiquent sa portée.
- Pour supprimer les fichiers et l'historique d'un document, utilisez **Supprimer le document** dans la colonne gauche.

Les pages PDF proviennent de l'extraction. Les DOCX/TXT utilisent des sections et blocs logiques. Une source existante ne garantit pas que le modèle en ait déduit chaque phrase correctement : vérifiez les réponses importantes. Aucun OCR ou benchmark synthétique n'est présenté comme une validation générale.

## Installation et développement

```powershell
cd C:\Dev\Xp_veille\localAI_analysedoc
.\installer.bat
.\.venv\Scripts\python.exe -m pytest -q
```

Backend :

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Frontend de développement, dans une autre console :

```powershell
cd web
npm run dev
```

Vite transmet `/api` au backend. Pour reconstruire l'interface servie par FastAPI, exécuter `npm run build` dans `web`, puis relancer le backend. Le port 8765 doit être libre. Les journaux du lancement Windows sont dans `data/server.log` et `data/server-error.log`.

Tests dans Edge sans téléchargement de navigateur : `cd web`, puis `npx playwright test`. Les scripts de benchmark utilisent le vrai serveur et le vrai modèle installé : `python -m scripts.benchmark` et `python -m scripts.benchmark_large` depuis l'environnement virtuel.

## Configuration

Variables facultatives, à définir avant lancement :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `LOCALDOC_MAX_UPLOAD_MB` | 100 | Taille maximale d'un fichier importé |
| `LOCALDOC_MAX_TEXT_MB` | 80 | Limite de texte extrait / taille DOCX décompressée |
| `LOCALDOC_DATA` | `data/` | Répertoire de stockage |

WebNN utilise le tokenizer du modèle sélectionné et un contexte de 3 072 tokens pour Qwen3 4B ou de 2 048 tokens pour les petits modèles. ONNX Runtime compte les opérations déléguées à WebNN. Certaines opérations ONNX peuvent rester sur le CPU. Les chemins de compatibilité des anciens benchmarks sont détaillés dans l'architecture.

Comparaison réelle sur un document déjà importé : `.\.venv\Scripts\python.exe -m scripts.benchmark_summary_modes IDENTIFIANT_DOCUMENT`. Le script utilise des copies isolées de la base, vide leurs caches uniquement, mesure les modes rapide et approfondi avec le même modèle CPU, puis leurs répétitions. Résultats : `docs/benchmark-summary-modes.json`. Suivi : `Get-Content data\summary-benchmark-progress.json`. Le temps d'extraction déjà payé est rapporté séparément. Ce script effectue de vrais calculs et remplace le rapport de ce nom ; conserver une copie avant de relancer une mesure datée.

Diagnostic du PDF de 111 pages et comparaison des résumés : [rapport](docs/RESUME_RAPIDE.md). Code et dépendances : [architecture](docs/ARCHITECTURE.md). Résultats mesurés et limites : [validation](docs/VALIDATION.md). Les versions exactes Python et npm sont verrouillées par `requirements.lock.txt` et `web/package-lock.json`. Les fichiers, bases, caches, dépendances et journaux ne sont pas destinés au partage du code source.
