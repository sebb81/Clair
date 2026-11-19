# Validation actuelle et limites connues

## Traduction documentaire ajoutée le 19 novembre 2026

Les tests Python couvrent le parcours ordonné de toutes les pages, la conservation des caractères sources lors du découpage, les titres reconnus, l'arrêt et la reprise sans recalcul des blocs réussis, la séparation des caches par langue/modèle/version, les réponses vides ou tronquées, l'export DOCX complet, les avertissements OCR, le redémarrage et la suppression des traductions avec leur document. Un test de déconnexion pendant une demande WebNN vérifie aussi l'annulation de la demande et la libération du verrou partagé.

Les tests d'interface avec API simulée couvrent le choix de langue, l'envoi explicite sur CPU, la progression, le lien d'export, le rechargement, l'erreur et la reprise. Les affichages bureau et mobile ont été inspectés ; le test mobile contrôle aussi l'absence de débordement horizontal. Ces simulations ne prouvent pas la qualité du modèle.

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
