> Archive : explication de la version indiquée dans le nom du fichier. Pour le fonctionnement actuel, consulter [l’index de la documentation](../README.md). Les liens des illustrations sont adaptés à cet emplacement.

# Validation et performances — 16 novembre 2026

## Ce qui est réellement vérifié

- **27 tests Python réussis**, dont une extraction synthétique de 3000 pages, l'arrêt du résumé, la reprise des anciennes synthèses et les nouvelles tentatives après troncature. Dernière suite complète : 17,85 s. Un avertissement de dépréciation Starlette concerne uniquement son client de test avec httpx.
- **3 tests de parcours Edge réussis**, en mode headless, en 28,5 s : import PDF/DOCX, vraie génération Ollama CPU, budget retrouvé, ouverture de la source page 2, historique après rechargement, démonstration, information absente, affichage mobile et arrêt d'un résumé du PDF réel avec conservation du cache.
- Build TypeScript/Vite réussi. Aucun modèle ni navigateur supplémentaire téléchargé.
- Lanceurs Windows vérifiés : `arreter.ps1` coupe bien le serveur, puis `demarrer.ps1` le relance et ouvre l'interface ; écoute confirmée uniquement sur `127.0.0.1:8765`.
- **0 requête navigateur vers un domaine externe**, connexions externes interceptées et bloquées pendant le parcours PDF. Aucune erreur JavaScript observée.
- Tests documentaires avec ouverture de sockets externes interdite ; les sockets loopback nécessaires à asyncio Windows restent autorisées.
- Audit Python des **28 paquets verrouillés** : aucune vulnérabilité connue retournée. Audit npm, dépendances de développement incluses : aucune vulnérabilité connue retournée. Ces audits ponctuels ne constituent pas une garantie future.

Le contrôle natif du navigateur/Windows était indisponible (`native pipe is unavailable`). Les parcours ont donc été exécutés dans Edge local par Playwright. Les captures ont ensuite été inspectées : [accueil](../accueil.png), [passage source](../sources.png), [mobile](../mobile.png).

## Correction du résumé réel de 111 pages

L'échec a été reproduit sur le premier regroupement du document : sortie JSON coupée à 320 tokens, `done_reason: length`, avant sa fermeture. Avec les nouvelles consignes et la réserve de sortie calculée après le prompt, ce lot s'est terminé en 23,21 s.

Les 185 synthèses locales existantes ont été conservées. Sur cette machine, passer les regroupements de 4096 à 16384 tokens réduit leur nombre de 57 à 7. Le premier grand lot testé s'est terminé en 87,22 s, avec environ 38 Go de RAM encore disponibles. La reprise complète, comprenant un regroupement déjà en cache et la synthèse globale, a duré 622,86 s ; la rédaction finale a duré 79,58 s. Ce temps ne comprend pas la préparation initiale des 185 lots.

La réponse finale s'est terminée avec `done_reason: stop`, 463 tokens de sortie, puis a été enregistrée en base et retrouvée dans Edge après rechargement, avec les cartes sources et sans bannière d'erreur. Le plan conserve les 299 fragments d'origine. Captures : [préparation](../summary-recovery-running.png), [résumé enregistré](../summary-complete.png). Les journaux de diagnostic contenant du texte utilisateur restent dans `data/`, exclu du partage du code.

Cette validation porte sur l'exécution, la couverture du plan, l'arrêt et la persistance. Le contrôle ponctuel du contenu a aussi révélé des citations imprécises : par exemple, des chiffres attribués à S107 et S176 se trouvent dans d'autres fragments, S110 et S180. La validation syntaxique des références ne valide pas leur correspondance sémantique ; la fidélité phrase par phrase reste à améliorer.

## Machine et réglages

Windows, Intel Core i9-13980HX, 24 cœurs physiques / 32 processeurs logiques ; environ 63,7 Gio de RAM visible. Python 3.11.7, Node 24.18.1, Ollama 0.40.16. Les benchmarks initiaux ci-dessous utilisent un contexte de 4096. Les regroupements de synthèse peuvent désormais utiliser 16384 sur cette machine ; les questions et le découpage initial restent à 4096. Maximum 8 threads et un calcul applicatif actif. Chaque appel demande `num_gpu: 0` et `think: false`.

Les réponses `/api/ps` indiquent **`size_vram: 0`** pour les deux modèles testés. Le runner actif a également été inspecté : **`-ngl 0 -c 4096 -t 8`**, enregistré dans `cpu-runner-flags.json`. Ce sont des générations CPU réelles, pas des réponses de démonstration codées en dur. Les données de démonstration sont synthétiques, le LLM ne l'est pas.

Deux modèles déjà présents ont été comparés : Qwen 3.5 2B (Q8_0) et Qwen 3.5 9B. Le 9B est préféré sur cette machine après revue des réponses ; le 2B reste sélectionnable. Le choix automatique du 9B exige au moins 24 Gio de RAM totale et 16 Gio disponibles ; il ne déclenche jamais son installation.

## Comparaison des approches sur un PDF de 4 pages

Le document Horizon contient objectif, responsable, budget de 240 000 euros pour 2027, tableau, risques et décisions. Les questions attendues sont dans `tests/fixtures/questions.json`. Les mesures ci-dessous viennent des derniers benchmarks enregistrés ; ce sont des essais individuels, pas des moyennes statistiques. Les longueurs de réponse diffèrent selon le modèle et la question.

| Approche / question | 2B : temps total client | 9B : temps total client | Appels 9B | Observation |
| --- | ---: | ---: | ---: | --- |
| Lecture directe, résumé global | 8,25 s | 33,28 s | 1 | Les quatre thèmes sont présents ; le 9B cite chaque thème. |
| Résumé hiérarchique, premier calcul de cette version | 32,80 s | 98,87 s | 6 | Quatre résumés de section, une synthèse globale puis une réponse. |
| Résumé + BM25, budget et risques | 7,59 s | 18,88 s | 1 | Réutilisation des synthèses existantes et ajout de passages originaux. |
| BM25, budget 2027 | 4,15 s | 8,83 s | 1 | 240 000 euros retrouvé, source PDF page 2. |
| BM25, responsable | 2,18 s | 5,08 s | 1 | Nadia Martin retrouvée, page 1. |
| TVA absente | 2,21 s | 5,17 s | 1 | « Information introuvable dans les passages consultés. » |
| Budget 2099 absent | 0,54 s | 0,37 s | 0 | Aucun passage correspondant à cette année ; aucune génération. |
| Lecture du chapitre 3 | 3,24 s | 9,47 s | 1 | Risques et calendrier de la section ciblée, page 3. |
| Résumé hiérarchique après cache | 8,35 s | 21,33 s | 1 | Aucun nouveau résumé intermédiaire calculé. |

Pour le 9B, la première synthèse consomme environ 77,0 s de préparation et le premier token de la réponse finale arrive à 83,4 s depuis la question. Avec les résumés en cache : préparation 0,32 s et premier token à 6,61 s. Pour le budget seul : premier token à 6,50 s, débit de génération observé 10,82 tokens/s. Le 2B produit approximativement 30 à 33 tokens/s sur ces essais ; le 9B approximativement 10 à 11.

**Compromis vérifié :** lecture directe préférable pour les petits documents ; hiérarchie utile pour dépasser le contexte et amortir la préparation ; BM25 utile pour revenir au texte original sur une question précise. Le premier passage hiérarchique est coûteux sur CPU. Le test hybride réutilise un cache déjà préparé : il ne faut pas comparer ses 18,88 s à un coût à froid.

## Qualité et erreurs observées

Les premiers prompts n'obtenaient pas toujours les citations. Les sorties intermédiaires sont désormais contraintes en JSON et les identifiants sont validés. Une référence inexistante est retirée, une synthèse structurée invalide n'est pas conservée.

Le **2B a déformé le sens des décisions** dans la synthèse hiérarchique. Une version disait qu'aucune décision n'était prise ; après resserrement des consignes, une autre écrivait « Le prestataire sélectionne quotidiennement la sauvegarde locale… ». Cette phrase n'est pas fidèle au texte. Les simples tests de présence de mots passent malgré cette erreur : ils ne suffisent pas à juger la fidélité.

Le **9B a correctement conservé**, sur ce document, la revue mensuelle des coûts, la sauvegarde locale quotidienne et le prestataire restant à sélectionner. Les sources correspondent aux pages attendues ; budget, responsable, risques et information absente ont été contrôlés. Cela ne prouve pas l'absence d'hallucination sur d'autres documents. Les citations vérifient l'existence des passages et permettent leur inspection, sans valider automatiquement chaque déduction.

Les tests de hiérarchie utilisent aussi un fournisseur factice pour vérifier couverture des fragments, interruption/reprise et invalidation des caches. Ils sont distincts des benchmarks réels ci-dessus et ne sont pas présentés comme des mesures de qualité du LLM.

## Extraction de 3000 pages : mesure distincte

PDF synthétique de **1 882 779 octets**, 4 textes simples répétés, un tableau ; 3000 pages et 3000 fragments. Le benchmark dédié a mesuré :

- Extraction : **8,98 s** ; temps total mesuré : 9,05 s.
- RSS avant extraction : 59,51 Mio.
- Pic RSS échantillonné : **67,50 Mio**, soit +7,98 Mio par rapport au départ.
- Échantillonnage demandé toutes les 20 ms ; 250 relevés, donc les intervalles effectifs peuvent dépasser 20 ms et manquer un pic court.
- **0 appel LLM** dans ce test.

La dernière suite complète a réextrait la fixture en 9,83 s. Ces résultats valident le parcours d'extraction d'un grand nombre de pages simples, pas le traitement de scans, de PDF de 100 Mo ni une analyse hiérarchique de 3000 pages réelles. Aucun temps d'analyse IA de 3000 pages n'est extrapolé.

Un relevé après les parcours indique backend 93,4 Mio et somme RSS Ollama + descendants 11 511,7 Mio, avec **2B et 9B simultanément chargés**. Cette somme peut compter de la mémoire partagée et inclut les processus Ollama préexistants ; elle ne représente pas la RAM propre au seul 9B. Les anciens champs RSS des benchmarks initiaux ne comptaient que les processus nommés Ollama ; le panneau actuel inclut aussi les runners enfants `llama-server.exe`. Voir `runtime-snapshot.json` pour le relevé corrigé.

## Limites non validées

- Analyse IA complète de 3000 pages réelles ; vitesse et fidélité sur un corpus métier.
- OCR : détection des scans testée, reconnaissance non implémentée.
- Extraction générale des tableaux sans bordures ou mises en page complexes.
- Coupure physique de la connexion Internet : non effectuée. Les tests bloquent les connexions externes documentaires et navigateur, le backend ne contacte que le loopback ; le processus Ollama préexistant n'a pas été placé dans un pare-feu de test.
- Installation sur un autre portable Windows et qualité des autres modèles proposés par Ollama.

## Reproduire

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s
cd web
npm run build
npx playwright test
cd ..
.\.venv\Scripts\python.exe -m scripts.benchmark_large
$env:BENCHMARK_MODEL='qwen3.5:9b'
.\.venv\Scripts\python.exe -m scripts.benchmark
.\.venv\Scripts\python.exe -m scripts.check_benchmark
```

Le serveur doit fonctionner sur le port 8765 pour les parcours navigateur et `scripts.benchmark`. Les benchmarks réels créent un document et son historique dans la bibliothèque locale. Les rapports bruts sont `benchmark-qwen3.5-2b.json`, `benchmark-qwen3.5-9b.json`, `benchmark-large.json` et les fichiers `*-checks.json`. Relancer avec un cache existant ne reproduit pas le coût initial.
