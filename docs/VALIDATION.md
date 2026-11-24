# Validation actuelle et limites connues

## Wllama CPU dans Edge

Wllama 4.0.0 et llama.cpp natif ont traité la même question budgétaire et le même résumé rapide dans Clair, sur le document Horizon. Le modèle était le même fichier Qwen3 4B Q4_K_M, avec 3 072 tokens de contexte et 8 threads. Les deux moteurs ont utilisé respectivement 412 et 608 tokens d'entrée pour les deux tâches. Chaque cas a été mesuré une fois sur le PC de développement.

| Mesure | Wllama CPU | llama.cpp CPU |
| --- | ---: | ---: |
| Question, premier accès au modèle | 40,48 s | 11,44 s |
| Résumé, fichier déjà en cache dans Edge pour Wllama | 47,54 s | 17,35 s |
| Pic de mémoire résidente échantillonné sur les deux tâches | 4,06 Gio (processus Edge) | 4,54 Gio (llama-server) |

Les réponses budgétaires donnent 240 000 euros pour 2027 avec les références [S2] et [S3]. Les résumés citent [S1] et [S2]. Dans Edge, le test a ouvert un passage cité puis annulé une autre demande Wllama. L'annulation libère le verrou et aucun message incomplet n'est ajouté à l'historique. Les requêtes observées par le test restent sur l'origine de Clair.

Le profil privé du premier essai a refusé la copie de 2,5 Go dans son cache. Le profil persistant utilisé pour les mesures a chargé le fichier complet. Le cache est propre au profil Edge et à l'origine locale. Pour rejouer le test, utilisez une bibliothèque de validation, définissez `CLAIR_REAL_WLLAMA_TEST=1` et exécutez `npx playwright test tests/wllama-real.spec.ts` depuis `web`. Les performances sur le Dell restent à mesurer.

## llama.cpp CPU dans Clair

Dans Edge, le choix **Qwen3 4B · llama.cpp (CPU)** a permis de poser une question et de lancer un résumé rapide sur le document de démonstration. Les deux réponses ont affiché **llama.cpp CPU** et des passages sources. L'essai a désactivé WebNN et a bloqué les requêtes du navigateur en dehors de Clair.

L'API a aussi terminé un résumé approfondi en trois appels, avec quatre sources et un seul chargement du moteur. Un autre essai a interrompu une génération après le premier jeton. Le processus local s'est arrêté, le verrou de calcul a été libéré et l'historique a conservé uniquement la réponse terminée.

Pour rejouer l'essai d'interface, installez le GGUF, démarrez Clair sur une bibliothèque de validation, puis exécutez `$env:CLAIR_REAL_LLAMACPP_TEST='1'` et `npx playwright test tests/llamacpp-real.spec.ts` depuis `web`. Le test crée puis supprime le document de démonstration de la bibliothèque de validation.

## Comparer WebNN CPU et llama.cpp sur Windows

Une fois Clair et les poids Qwen3 4B WebNN installés, exécutez cette commande dans PowerShell depuis la racine du projet.

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_cpu
```

Au premier lancement, le banc télécharge environ 2,5 Go pour le GGUF officiel de Qwen et le binaire CPU Windows x64 de llama.cpp. Il vérifie leurs SHA-256. Les exécutions suivantes réutilisent ces fichiers. Le banc relève le processeur, la RAM et les instructions AVX2 et AVX‑512F exposées par Windows, puis teste 2, 4 et 8 threads avec trois répétitions pour une lecture de 512 tokens et une génération de 64 tokens.

La comparaison utilise le worker WebNN de Clair dans une instance Edge isolée et llama-server sur localhost. Les moteurs traitent les mêmes extraits synthétiques et les mêmes consignes, avec un contexte de 3 072 tokens. La question factuelle démarre dans une nouvelle session et le résumé court suit avec le modèle chargé. Le cache disque de Windows suit son fonctionnement normal. Le cache du prompt est désactivé côté llama.cpp. Le banc mesure la génération et exclut l'import, la recherche et la validation des citations de l'application. Pour comparer les mesures à froid, ajouter `server_load_ms` au premier `elapsed_ms` de llama.cpp. Dans le relevé WebNN, la première durée inclut déjà le chargement.

Chaque dossier `data/cpu-bench/run-…/` contient les résultats de `llama-bench`, les réponses des deux moteurs, les durées par phase et les pics mémoire échantillonnés. Le relevé natif couvre le processus llama-server et celui de WebNN couvre les processus de l'instance Edge. Utiliser le même poste et garder des conditions de charge comparables pour interpréter les écarts.

Sur l'i9‑13980HX de développement, Windows expose AVX2. Le binaire officiel b12650 a choisi `ggml-cpu-alderlake.dll`. Les moyennes de trois répétitions sont les suivantes.

| Threads | Traitement du prompt (tokens/s) | Génération (tokens/s) |
| ---: | ---: | ---: |
| 2 | 44,85 | 11,94 |
| 4 | 79,18 | 18,00 |
| 8 | 135,03 | 21,92 |

Les deux moteurs ont donné la même réponse factuelle, **240 000 euros en 2027 [S2]**, sur une entrée de 311 tokens. Le délai complet était de **5,94 s avec llama.cpp** et de **66,34 s avec WebNN**. Le prétraitement WebNN a évalué un graphe dimensionné à 3 072 tokens. Le pic résident observé était d'environ **4,6 Gio** pour llama-server et **24,4 Gio** pour les processus Edge du banc.

Les deux résumés ont atteint le premier plafond de 96 tokens. Avec un nouveau démarrage et un plafond de 160 tokens, le même résumé a abouti en **11,83 s avec llama.cpp** (144 tokens, fin naturelle) et **105,11 s avec WebNN** (121 tokens, fin naturelle). Les deux sorties citent `[S2]`, `[S3]` et `[S4]`. WebNN conserve la distinction entre un budget 2028 absent des extraits et un budget inexistant. La formulation « avec aucun budget indicatif pour 2028 » de llama.cpp est moins précise.

Ces résultats comparent le GGUF Q4_K_M au modèle ONNX quantifié dans leurs moteurs respectifs. Chaque tâche documentaire a été mesurée une fois par configuration. Le Dell cible et les parcours documentaires complets restent à mesurer.

## Bergamot dans Clair le 23 novembre 2026

Le binaire Windows et les deux modèles ont été installés via `installer-traduction.bat`. Le parcours réel dans Edge a traduit du français vers l'anglais et de l'anglais vers le français avec WebNN désactivé dans les tests. Les deux exports DOCX ont abouti avec des événements indiquant le moteur Bergamot sur CPU.

Sur le PC de développement, la traduction du PDF synthétique Horizon de quatre pages a pris **1,12 s**, démarrage du moteur compris et extraction exclue. Le DOCX contient les huit blocs et les quatre repères de page. Les dates, le montant et le nom vérifiés sont présents. La relecture a cependant relevé deux erreurs de vocabulaire. « Numerisation » est devenu « Number » et « indisponibilite » a donné « unspoilability ». Le test de reprise sur vingt pages a interrompu la demande après un bloc, puis traduit les 39 blocs restants. Le processus a été fermé à l'arrêt et à la fin.

Pour rejouer les essais d'interface, installez Bergamot, démarrez Clair, puis exécutez `$env:CLAIR_REAL_BERGAMOT_TEST='1'` et `npx playwright test tests/translation-real.spec.ts --grep Bergamot` depuis `web`. Bergamot reste une option. La vitesse et la qualité sur un document représentatif du Dell cible restent à mesurer.

## Mémoire et traduction le 20 novembre 2026

Correction : la traduction utilise un contexte de 1 024 tokens, au lieu du contexte général de 3 072 tokens de Qwen3. Les blocs sources restent limités à 240 tokens. La sortie dispose de 512 tokens ; un dépassement entraîne toujours une subdivision sans suppression du texte source. Les deux sessions ONNX restent chargées entre blocs d'une même demande, puis sont libérées avec le contexte WebNN à la fin, en cas d'erreur ou d'arrêt. Les questions et préparations libèrent le moteur après 30 secondes d'inactivité. Un moteur bloqué est terminé après deux secondes d'attente de fermeture.

**69 tests Python réussis**, un test lent d'extraction non exécuté ; build TypeScript/Vite réussi ; **11 tests d'interface simulés réussis**, dont la réutilisation entre blocs et la libération différée/immédiate ; **un parcours réel français → anglais avec export DOCX réussi** sur une base isolée. Le DOCX a été rouvert et le montant, la date et les négations vérifiés. Aucun appel externe ni erreur JavaScript n'est observé par ce parcours réel. La session de l'utilisateur, qui signalait un calcul actif, n'a pas été redémarrée.

Le banc `web/scripts/benchmark-translation.mjs` utilise une instance Edge 157 séparée, deux passages français synthétiques identiques, les poids installés, le contexte CPU WebNN et aucune réponse en cache. Les métriques de mémoire additionnent uniquement les processus de cette instance Edge (y compris son service de calcul). Chaque valeur ci-dessous vient d'un seul passage du banc ; un calcul restait actif dans l'instance utilisateur. Ce n'est pas une garantie de vitesse sur un autre PC ou un long document.

| Mesure | Qwen3 avant, 3 072 tokens | Qwen3 corrigé, 1 024 tokens | Qwen2.5 1,5B, 1 024 tokens |
| --- | ---: | ---: | ---: |
| Premier bloc, chargement compris | 134,98 s | 98,74 s | 37,33 s |
| Chargement/compilation du premier bloc | 82,67 s | 83,84 s | 32,10 s |
| Deuxième bloc, modèle déjà chargé | 43,55 s | 15,40 s | 5,01 s |
| Mémoire privée après le deuxième bloc | 23,14 Gio | 22,89 Gio | 9,70 Gio |
| Pic de mémoire privée au chargement/calcul | 27,64 Gio | 25,97 Gio | 12,80 Gio |
| Pic de mémoire résidente | 24,64 Gio | 25,07 Gio | 11,36 Gio |

Avec Qwen3, les deux sorties sont identiques avant/après (146/141 tokens d'entrée, 40/37 tokens de sortie, 41/38 exécutions WebNN). Le deuxième bloc est 2,83 fois plus rapide. **La réduction de contexte ne diminue pas sensiblement la mémoire occupée par le modèle chargé** ; le pic résident n'est pas réduit dans cet essai. L'amélioration mémoire principale est la libération automatique après la demande : l'instance corrigée revient à 0,64 Gio de mémoire résidente, avec confirmation de fermeture des sessions et du contexte. Le banc de référence ferme également son worker manuellement à la fin, contrairement à l'ancienne interface qui le conservait sans délai.

Qwen2.5 1,5B conserve montant, dates, lieu, durée et négations sur ces deux passages, mais ajoute `END TRANSLATION` à la seconde sortie. Ce modèle reste une option manuelle dans les paramètres ; il ne remplace pas automatiquement Qwen3. Ces exemples ne valident ni la fidélité sur de longs documents ni les autres langues. Les rapports complets restent dans `data/translation-memory/{baseline,optimized,economical}.json` ; ils comprennent textes, métriques, échantillons mémoire et fermeture du moteur.

Reproduction : démarrer Clair ; dans `web`, exécuter `node scripts/benchmark-translation.mjs baseline`, puis `node scripts/benchmark-translation.mjs optimized` et, facultativement, `node scripts/benchmark-translation.mjs economical`. Les deux premières variantes gardent les mêmes poids Qwen3 ; la troisième change explicitement de modèle. Pour le parcours réel isolé, `CLAIR_TEST_URL` peut désigner un second serveur local sur le port 5173, puis activer `CLAIR_REAL_TRANSLATION_TEST=1` et `CLAIR_REAL_DEVICE=cpu` avant `npx playwright test tests/translation-real.spec.ts`.

Une lecture rembourrée de 512 tokens avec un cache de 1 024 tokens a été essayée et écartée : cet export déplace alors ses opérations d'attention sur le CPU de secours et échoue à l'exécution. Le worker conserve donc une lecture de même dimension que son cache. Un build ou des tests simulés ne suffisaient pas à détecter cette incompatibilité.

## Choix CPU GPU NPU commun aux fonctions le 19 novembre 2026

Vérification de cette modification : **68 tests Python réussis**, un test lent d'extraction non exécuté ; compilation Vite/TypeScript réussie ; **9 tests d'interface réussis** avec moteur/API simulés ; **2 essais réels réussis** dans Edge. Les tests simulés couvrent les priorités NPU/GPU, le repli, la mémorisation des échecs, le nouveau test volontaire, le CPU sans essai accélérateur, l'arrêt sans repli, le délai d'expiration et l'échec de tous les périphériques. Les tests Python vérifient la transmission des quatre préférences aux questions, préparations et traductions, ainsi que la reprise d'une traduction avec des blocs CPU conservés et des blocs NPU simulés.

Sur le PC de développement, la question factuelle avec **Qwen2.5 1,5B et priorité GPU** s'est terminée avec un contexte GPU, après le test de génération du modèle. Le dernier appel enregistre 59 exécutions WebNN. Le montant 240 000 euros a été trouvé, mais le modèle a aussi ajouté une phrase contradictoire disant l'information introuvable : cet essai valide le chemin matériel, pas la fidélité générale du modèle.

La traduction française → anglaise avec **Qwen3 4B et choix automatique** a essayé NPU puis GPU. Les deux ont échoué à la compilation du graphe (`MLGraphBuilder` / création de session). Le repli CPU a terminé la traduction avec 41 exécutions WebNN. Le DOCX reprend le montant, la date et les deux négations du petit exemple. Le bandeau de l'interface et ses détails ont été inspectés sur ces deux essais. Aucun appel externe ni erreur JavaScript n'a été observé ; les deux documents synthétiques ont été supprimés après contrôle. Les deux tests réunis prennent environ 2 min 36, chargements et interface compris, sans protocole de comparaison de vitesse.

Aucun NPU n'a été identifié dans l'inventaire matériel de ce PC de développement. **Aucune génération réelle sur NPU n'est donc validée par ces essais**. Le succès d'une création de contexte ne suffit pas : il faut que le modèle compile et génère correctement sur le PC équipé du NPU. La disponibilité dépend aussi de Windows, d'Edge, des pilotes et des opérations du modèle ([options ONNX Runtime Web](https://onnxruntime.ai/docs/api/js/interfaces/InferenceSession.WebNNContextOptions.html), [limites et replis d'opérateurs](https://onnxruntime.ai/docs/tutorials/web/ep-webnn.html)). Le logiciel affiche un contexte demandé et exécuté, pas une certification d'affectation de chaque opération à une puce.

Reproduction : démarrer Clair, puis dans `web`, lancer `npx playwright test tests/devices.spec.ts tests/translation.spec.ts tests/summary-fast-ui.spec.ts`. Pour les calculs réels, définir `$env:CLAIR_REAL_DEVICE_TEST='1'`, `$env:CLAIR_REAL_TRANSLATION_TEST='1'`, `$env:CLAIR_REAL_DEVICE='auto'`, puis lancer `npx playwright test tests/devices-real.spec.ts tests/translation-real.spec.ts`. Le test de question choisit explicitement la priorité GPU ; la traduction utilise la préférence passée par la variable. Les captures restent dans les résultats locaux des tests.

## Traduction documentaire ajoutée le 19 novembre 2026

Les tests Python couvrent le parcours ordonné de toutes les pages, la conservation des caractères sources lors du découpage, les titres reconnus, l'arrêt et la reprise sans recalcul des blocs réussis, la séparation des caches par langue/modèle/version, les réponses vides ou tronquées, l'export DOCX complet, les avertissements OCR, le redémarrage et la suppression des traductions avec leur document. Un test de déconnexion pendant une demande WebNN vérifie aussi l'annulation de la demande et la libération du verrou partagé.

Les tests d'interface avec API simulée couvrent le choix de langue, la transmission du choix matériel commun, la progression, le lien d'export, le rechargement, l'erreur et la reprise. Les affichages bureau et mobile ont été inspectés ; le test mobile contrôle aussi l'absence de débordement horizontal. Ces simulations ne prouvent pas la qualité du modèle. Le premier essai décrit ci-dessous utilisait le CPU forcé ; le choix commun GPU/NPU l'a remplacé dans la version actuelle.

Un essai réel dans Edge avec **Qwen3 4B sur CPU** a importé un TXT synthétique en français et téléchargé le résultat anglais en DOCX. Le fichier obtenu contient : « The budget is 240,000 euros. The launch is scheduled for September 2027. » puis « The vendor has not been selected yet. No final decision has been made. » Le montant, la date et les deux négations du texte d'entrée sont conservés sur cet exemple. Le test complet prend environ 1 min 30 sur le PC de développement, chargement et interface compris ; ce n'est pas un benchmark de débit. Aucun appel externe ni erreur JavaScript n'a été observé. Le document synthétique de validation a ensuite été supprimé de la bibliothèque.

Le DOCX a été rouvert avec python-docx pour vérifier ses paragraphes, son titre et son repère source. Son rendu dans Word/LibreOffice n'a pas été vérifié. Le test réel porte sur un petit TXT français → anglais ; les autres langues, les longs documents et la fidélité des tableaux ne sont pas validés par cet essai. Les PDF et DOCX utilisent le même texte extrait, avec des vérifications automatisées de parcours et d'export. L'application ne réalise pas d'OCR et ne reconstruit pas la mise en page d'origine.

Pour reproduire sans calcul réel : `.\.venv\Scripts\python.exe -m pytest -q -m "not slow"`, puis dans `web`, `npx playwright test tests/translation.spec.ts tests/summary-fast-ui.spec.ts`. Pour l'essai réel, démarrer Clair, définir `$env:CLAIR_REAL_TRANSLATION_TEST='1'` puis lancer `npx playwright test tests/translation-real.spec.ts` dans `web`. Ce dernier utilise les fichiers locaux de Qwen3 4B et enregistre un DOCX synthétique dans `data/translation-validation/`.

## Qwen3 4B dans Clair le 19 novembre 2026

Qwen3 4B est recommandé quand il est installé. Le graphe local adapte l'[export ONNX publié par WebAI Community](https://huggingface.co/webai-community/ai-models/blob/main/Qwen3-4B/README.md) et conserve ses poids quantifiés. L'installation depuis les poids téléchargés a reproduit les cinq fichiers actifs à l'identique (SHA-256).

Dans Edge 157, un test isolé sur CPU a retrouvé 240 000 euros et la bonne citation (24 exécutions WebNN, 81,56 s à froid, à 2 048 tokens). Sur ce PC, l'export adapté échoue à compiler sur GPU. Une autre adaptation a compilé, puis échoué au test de génération. Clair poursuit via WebNN sur CPU. Le CPU est le périphérique utilisé dans les essais réussis de ce modèle.

Le bouton **Résumé** a produit cinq paragraphes rédigés et cité cinq pages (1, 14, 25, 31 et 33) sur le PDF de 111 pages. La sélection avait fourni des passages de 18 pages. La génération à froid a pris 295 s, dont 17 s pour l'essai GPU et 41 s pour charger et compiler le modèle sur CPU. Les mesures enregistrent un appel, 2 105 tokens d'entrée, 347 en sortie et 348 exécutions WebNN. Une carte source a été ouverte dans Edge. Le résumé reste centré sur le début du dossier et simplifie l'intitulé de la certification. Une autre consigne, écartée, inventait l'obtention de la certification et des références.

L'[export étudié de Qwen3.5 4B](https://huggingface.co/webai-community/ai-models/blob/main/Qwen3.5-4B/README.md) cible WebGPU et utilise des opérateurs de gestion d'état que le chemin WebNN de Clair ne prend pas en charge. Le modèle installé est Qwen3 4B. L'équivalence de qualité avec Qwen3.5 9B reste à établir.

## Comparaison WebNN du 19 novembre 2026

Le worker de Clair a exécuté les mêmes requêtes dans Edge 157 sur le PC de développement équipé d'une RTX 4080 Laptop. Le test compare une question factuelle, un court résumé de trois faits et un résumé d'une même sélection d'environ 1 050 tokens tirée du PDF de 111 pages. Il n'ouvre pas la bibliothèque en écriture. Le contexte est fixé à 2 048 tokens et le cache de réponses est absent. La première requête de chaque session comprend le chargement et, côté GPU, le test de génération. Les autres utilisent le modèle chargé. Il s'agit d'une exécution par cas, avec des longueurs de sortie différentes.

| Modèle et demande WebNN | Question factuelle à froid | Résumé court à chaud | Extraits du PDF de 111 pages à chaud |
| --- | --- | --- | --- |
| Qwen2 0,5B, CPU | 14,06 s, montant trouvé mais sortie tronquée | 7,02 s, trois faits repris | 11,27 s, sortie tronquée |
| Qwen2.5 1,5B, GPU | 14,61 s, réponse exacte et citation S1 | 3,26 s, gabarit JSON recopié au lieu du résumé | 22,40 s, sortie tronquée |
| Qwen2.5 1,5B, CPU | 36,00 s, réponse exacte et citation S1 | 21,01 s, faits principaux repris, calendrier attribué à la mauvaise source | 12,40 s, JSON complet, très partiel et citations qui ne soutiennent pas toutes les affirmations |
| Phi-4 Mini, CPU | 58,42 s, réponse exacte et citation S1 | 20,95 s, JSON invalide | 39,44 s, JSON invalide et faits à vérifier |

Le test de génération GPU de Qwen2 0,5B échoue. Phi-4 Mini échoue à compiler sur GPU. Une consigne en puces a également été essayée pour Qwen2.5. Elle ne résout pas la troncature sur le long extrait et les références restent incomplètes. Les temps ne prouvent pas un gain général sur les résumés ni la compatibilité avec le Dell.

Qwen2.5 1,5B est disponible dans Clair comme deuxième modèle WebNN. Le choix **Calcul WebNN** permet de comparer le mode automatique et le CPU. Les réponses enregistrées distinguent le modèle, le matériel demandé et la réutilisation du cache. Après simplification de la consigne factuelle, un test dans l'interface a retrouvé les 240 000 € du PDF Horizon. La page 2, qui contient le montant, figurait parmi les passages proposés, mais le modèle a indiqué le mauvais identifiant dans son texte. Cette vérification est distincte des mesures du banc ci-dessus.

Pour reproduire les essais, générez les requêtes avec `.\.venv\Scripts\python.exe -m scripts.prepare_webnn_benchmark`, puis lancez `node web/scripts/benchmark-webnn.mjs qwen2 qwen25-15b` après avoir compilé le frontend. Les résultats bruts sont dans `data/webnn-bench/`. Ils contiennent des extraits du PDF local et ne sont pas destinés au partage. L'essai Phi-4 Mini utilise l'[export WebNN](https://huggingface.co/webnn/Phi-4-mini-instruct-onnx-webnn) dans `data/webnn-bench/phi4-mini/`, avec `model.onnx`, `model.onnx.data`, `tokenizer.json` et `tokenizer_config.json` au même niveau.

## Mesures historiques Ollama

État de référence : **18 novembre 2026**. Documentation confrontée au code et aux rapports à cette date. Les résultats ci-dessous sont ceux des essais enregistrés ; la relecture documentaire ne constitue pas une nouvelle exécution du modèle.

## État de validation

| Sujet | Preuve disponible | Conclusion permise |
| --- | --- | --- |
| Résumé rapide et approfondi sur 111 pages | Vraies générations Qwen 3.5 9B Q4_K_M CPU, mêmes PDF et poids, copies de base isolées | Le gain de temps est mesuré dans cet essai. |
| Cache de réponse | Répétition exacte de chaque demande | Environ 0,30 s et zéro appel ; ce n'est pas une nouvelle lecture du document. |
| Fonctionnement Python | 42 tests ciblés réussis lors de l'implémentation du 18 novembre | Routage, budget, sources, caches, reprise, interruption et métriques testés ; les doubles de modèle ne prouvent pas sa qualité. |
| Construction de l'interface | TypeScript/Vite réussis le 18 novembre | L'interface peut être construite avec ces sources. |
| Affichage de la couverture | Un parcours Edge réussi le 18 novembre avec API simulée | Options rapide/approfondi, couverture partielle et cartes de pages affichées ; pas une génération réelle dans ce parcours. |
| Fidélité du contenu | Relecture de résumés et passages originaux du PDF | **Validation partiellement négative : erreurs et omissions subsistent.** |
| Autre poste, dont Dell cible évoqué précédemment | Aucun nouvel essai de ces deux modes sur ce poste | Aucun facteur d'accélération garanti sur une autre machine. |

Source principale : [benchmark-summary-modes.json](benchmark-summary-modes.json), notamment `runs`, `comparison`, `quality_review` et `validation`. Le [rapport détaillé](RESUME_RAPIDE.md) donne le diagnostic et les temps par appel.

## Comparaison mesurée du 18 novembre

Le PDF compte 111 pages, 299 fragments et 105 sections détectées. L'extraction, déjà faite, avait pris 8,245 s. Les deux stratégies utilisent son texte existant, des caches applicatifs vides et un modèle préchargé. Les durées ci-dessous vont du lancement de la demande à sa réponse complète ; elles excluent extraction et préchargement.

| Mode | Durée totale | Appels du pipeline | Tokens d'entrée | Tokens de sortie |
| --- | ---: | ---: | ---: | ---: |
| Rapide final | 243,294 s — **4 min 03 s** | **1** | 7 098 | 564 |
| Approfondi optimisé | 1 101,443 s — **18 min 21 s** | **6** | 48 539 | 1 551 |
| Rapide, répétition exacte | 0,304 s | 0 | 0 | 0 |
| Approfondi, répétition exacte | 0,301 s | 0 | 0 | 0 |

Le rapide est **4,527 fois plus rapide**, avec **77,911 % de temps en moins** et **85,377 % de tokens d'entrée en moins**, dans cet essai. Chaque préchargement ajoute un appel hors chronomètre, consigné séparément dans `warmup`.

Un premier rapide, avant renforcement de la consigne, avait pris 181,837 s. Il reste dans `superseded_runs` ; il n'entre pas dans le gain final. Le modèle est déchargé et préchargé avant chaque mode, mais la température du CPU et la charge du système ne sont pas neutralisées statistiquement. Les débits observés varient entre essais. Il n'y a qu'une mesure retenue par mode.

Le calcul est CPU : `num_gpu: 0`, zéro VRAM observée, runner avec `-ngl 0`, huit threads et un seul calcul parallèle observé. Les contextes de l'essai sont 8 192 pour le rapide, 16 384 pour la préparation approfondie et 4 096 pour sa réponse finale. Tous les appels retenus finissent par `stop`, sans nouvelle tentative ; aucun caractère Thinking n'est reçu.

## Ce que la couverture indique

Le contexte rapide contient 77 passages, représentant 80 identifiants de fragments, répartis sur 62 pages et 50 sections. Des passages des quatre chapitres sont présents dans l'entrée. Le résumé final cite quinze identifiants sur douze pages, sans restitution distincte des quatre chapitres.

L'approfondi parcourt les 299 fragments sur les 111 pages enregistrées. Son résumé final ne cite que six identifiants sur cinq pages. La couverture du plan de lecture est donc plus large que celle de ses citations finales.

Le texte extrait peut se limiter à une légende ou un pied de page là où une image contient l'information principale. « Tous les blocs extraits parcourus » ne signifie pas que toutes les informations visuelles du PDF sont lues.

## Erreurs observées et portée des sources

| Observation | Texte ou page à vérifier | Limite constatée |
| --- | --- | --- |
| Le rapide affirme un respect du RGAA. | Page 81, S278/S280 : conformité non démontrée ; page 32, S139 : recommandations d'accessibilité. | La réserve de la page 81 n'était pas sélectionnée. Une recommandation suivie est présentée comme une conformité. |
| Le rapide présente des contraintes SQL comme réalisées. | Page 36, S151/S152 : contrôles applicatifs employés et architecture SQL envisagée. | Confusion entre réalisation et possibilité. |
| Le rapide conserve certaines réserves. | Pages 37 et 43, S156/S174. | Il distingue des activités proposées et une architecture complète encore non réalisée ; cette réussite ponctuelle ne corrige pas les autres erreurs. |
| L'approfondi présente les 500 utilisateurs comme une capacité effective. | Page 31, S134 : hypothèse de planification. | Perte du statut d'hypothèse pendant la condensation. |
| L'approfondi affirme une non-conformité RGAA. | Page 81 : conformité non démontrée. | L'absence de démonstration devient une conclusion négative non justifiée. |
| Des références existent mais justifient mal leur paragraphe. | Voir les réponses et `quality_review` dans le rapport brut. | Les contrôles d'identifiants ne constituent pas une validation factuelle. |

**La performance est validée sur ce document et cette machine. La fidélité complète et l'exhaustivité ne le sont pas.** Le mode approfondi reste disponible pour parcourir tous les fragments ; son coût supérieur ne garantit pas une meilleure fidélité. Les réponses importantes demandent une consultation du texte original.

## Tests fonctionnels et preuves historiques

Les tests Python de hiérarchie et de cache utilisent aussi des réponses de modèle simulées pour contrôler le mécanisme. Le test Edge récent utilise une API simulée pour l'affichage. Les chiffres de durée du tableau viennent du vrai moteur appelé avec le vrai Ollama local, séparément.

Le test de stress d'extraction de 3 000 pages n'a pas été relancé le 18 novembre. Le rapport [benchmark-large.json](benchmark-large.json), du 16 novembre, mesure seulement une extraction synthétique simple et zéro appel LLM. Les trois anciens parcours Edge réels, les anciens essais 2B/9B, les contrôles réseau et l'audit de dépendances restent documentés dans la [validation historique du 16 novembre](historique/VALIDATION_2026-11-16.md).

L'audit de dépendances ancien n'est pas un audit de la liste actuelle, qui a évolué. Les anciens PID, mesures de RAM, vitesses et captures ne sont pas présentés comme l'état actuel de l'application.

## Vérifications encore manquantes

- Fidélité phrase par phrase sur un corpus varié et capacité à conserver toutes les réserves importantes.
- Même comparaison de performance sur le poste de déploiement réel.
- OCR et interprétation des images, tableaux complexes et mises en page difficiles.
- Résumé IA complet de milliers de pages réelles ; le test d'extraction ne permet pas d'en déduire le temps.
- Nouveau contrôle de sécurité et de dépendances après les ajouts du 18 novembre.

## Reproduire sans confondre les essais

Depuis la racine du projet, pour les tests Python ciblés :

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not slow"
```

Pour construire et vérifier l'affichage récent, avec le serveur local démarré :

```powershell
cd web
npm.cmd run build
npx.cmd playwright test tests/summary-fast-ui.spec.ts
```

Pour refaire la comparaison réelle, depuis la racine, hors d'un autre calcul Ollama :

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_summary_modes 30a5b4ef7fb945d5eb37a401
Get-Content data\summary-benchmark-progress.json
```

Cette dernière commande utilise le PDF déjà importé et crée des copies isolées de la base. Elle produit de vraies générations, peut prendre plusieurs dizaines de minutes et remplace le rapport `benchmark-summary-modes.json` : conserver une copie du rapport daté avant de refaire l'essai. Le serveur HTTP n'est pas requis pour ce script, qui appelle directement le moteur et Ollama. Les anciens scripts de benchmark et leurs prérequis restent décrits dans les archives.
