> Archive : explication de la version indiquée dans le nom du fichier. Pour le fonctionnement actuel, consulter [l’index de la documentation](../README.md). Les liens des illustrations sont adaptés à cet emplacement.

# Clair : analyse documentaire locale

Application monoposte : React/TypeScript/Vite servi par FastAPI sur `127.0.0.1:8765` ; SQLite et fichiers dans `data/` ; inférence Ollama sur l'adresse fixe `http://127.0.0.1:11434`. Aucun embedding ni index vectoriel. Aucun outil exécutable exposé au modèle.

## Choix examinés avant développement

| Solution | Possibilités et décision V1 |
| --- | --- |
| [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/page.html) | Extraction page par page, sommaire PDF, tableaux par `find_tables()`. Retenu pour une extraction légère sans modèle de mise en page. Les tableaux sans bordures et documents multicolonnes restent difficiles. Licence AGPL/commerciale : tenir compte de ce choix avant redistribution propriétaire. |
| [Docling](https://docling-project.github.io/docling/usage/advanced_options/) | Structure plus riche, tableaux et OCR, mode hors ligne avec modèles préparés. Non installé : ses modèles de mise en page et dépendances augmenteraient le coût initial. Extension possible, uniquement après préparation explicite des ressources locales. |
| [Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md) | API locale, streaming NDJSON, métriques de génération. Retenu car déjà installé avec des poids locaux. Aucun endpoint de téléchargement n'est appelé. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Inférence CPU GGUF et serveur local. Alternative pertinente pour maîtriser directement le runtime ; pas de second fournisseur à entretenir dans cette V1. |
| [LlamaIndex Tree Summarize](https://developers.llamaindex.ai/python/framework/module_guides/querying/response_synthesizers/) | Agrégation récursive de résumés ; stratégie retenue, framework non installé. Quelques fonctions suffisent ici pour contrôler les caches et les références. |
| [SQLite FTS5](https://www.sqlite.org/fts5.html) | Index textuel persistant et BM25 natif. Retenu : pas d'index Python complet en RAM. Les scores les plus bas sont les meilleurs. |
| python-docx | Paragraphes, titres et tableaux dans l'ordre du document. Pas de pagination physique inventée. |

## Circuit des données

1. Import : lecture de l'upload par blocs, SHA-256, limites de taille, validation des signatures, stockage sous nom interne. Le nom utilisateur n'est pas un chemin de stockage.
2. Extraction : PDF page par page ; TXT UTF-8 par blocs ; DOCX via le parseur XML de python-docx avec une limite de taille décompressée. Les images ne sont jamais envoyées au modèle. Un scan sans texte provoque un avertissement OCR. OCR non implémenté en V1.
3. Niveaux 0/1 : texte original, tableaux, pages/blocs, sections et fragments SQLite. Détection des titres par sommaire PDF et règles textuelles ; elle reste heuristique, notamment sans styles DOCX.
4. Niveau 2 : lots de fragments contigus, y compris à travers les petites sections ; résumé local avec sortie JSON contrainte et identifiants de sources autorisés. Les anciens lots déjà en cache gardent leur position et sont réutilisés.
5. Niveau 3 : réduction des lots de résumés, avec un contexte de regroupement plus large si la RAM le permet ; liens vers tous les fragments d'origine conservés séparément du texte résumé.
6. Niveau 4 : synthèse globale. Maximum 12 réductions et arrêt si la taille ne diminue plus. Les niveaux 3 ne sont nécessaires que si la taille l'exige. Une taxonomie universelle chapitre/sous-section n'est pas garantie.
7. Réponse : lecture directe, section ciblée, BM25 ou synthèse + BM25. L'interface reçoit des événements `status`, `token`, `done`, `error`. L'événement final remplace le texte provisoire après vérification syntaxique des références.

## Contexte et frugalité

Contexte des questions et du découpage initial : 4096 tokens. Le contexte des regroupements passe à 16384 si la machine dispose d'au moins 32 Go de RAM totale et 16 Go disponibles au démarrage ; sinon il reste à 4096. Il est configurable par `LOCALDOC_SUMMARY_CONTEXT`. Sortie finale : 640 tokens. Les lots visent 70 mots, la synthèse globale 160 ; chaque sortie dispose d'au plus 768 tokens, bornés par la place restante après le prompt réel estimé. Une troncature déclenche au plus une seconde tentative plus concise, avec au plus 1024 tokens disponibles. Aucun texte tronqué n'est mis en cache. La réserve de découpage historique de 320 reste identique pour réutiliser les lots existants.

Le budget conservateur est fondé sur les octets UTF-8 et une réserve pour le prompt et le gabarit. Ce budget est une estimation ; `prompt_eval_count` et `eval_count` sont les comptes observés retournés par Ollama. Un fragment trop grand, une lecture directe partielle et une hiérarchie qui ne diminue plus provoquent une erreur explicite.

La version transmise du prompt (`compact-v1`) reformule les mêmes règles plus brièvement et ne répète pas tous les identifiants de sources dans une seconde liste. Elle supprime seulement les espaces des lignes vides et limite les sauts de ligne consécutifs ; le contenu lexical, les tabulations et l'indentation des sources restent inchangés. En sortie JSON intermédiaire, les références sont demandées dans `source_ids` seulement, puis ajoutées par l'application après validation. Pour les questions, `pack` regroupe seulement les couples titre/texte strictement identiques, avec tous leurs identifiants. Aucun filtrage des mots courants ni sélection sémantique supplémentaire n'est appliqué.

Le prompt canonique et ses budgets historiques sont conservés pour réutiliser les lots et les synthèses déjà calculés. Cette modification compatible du libellé transmis ne force pas leur recalcul. Les réponses finales utilisent une nouvelle version de clé incluant le prompt compact ; l'historique reste conservé. `prompt_bytes_saved` mesure les octets évités par rapport au prompt canonique, pas un nombre exact de tokens. Seul `prompt_tokens` est le compte réel d'Ollama.

Un seul calcul IA actif, 8 threads au maximum, `num_gpu: 0`, température 0 et raisonnement désactivé. Le CPU est demandé à chaque appel ; `size_vram` retourné par `/api/ps` sert de vérification matérielle. La RAM mesurée par l'application est le RSS backend et la somme des RSS des processus Ollama, pas une mesure de mémoire physique unique ni un plafond dur.

Le cache d'extraction dépend du hash et de la version du parseur. Le cache de résumé dépend du digest des poids, du contexte, du nombre de threads, de la version des prompts, du niveau, du contenu et des références d'origine. La taille du fichier ne déclenche pas de téléchargement ni de préparation IA automatique. Les résumés sont préparés explicitement, ou à la demande d'une question globale trop longue.

Les tables additives `summary_roots` et `answer_cache` ne modifient ni les documents ni les synthèses existantes. `summary_roots` pointe vers une synthèse globale validée pour éviter de reparcourir tous les lots. `answer_cache` conserve une réponse finale avec ses sources et avertissements, uniquement si la génération se termine normalement avec des références autorisées. Sa clé inclut le document, le digest et le nom du modèle, la question exacte, la stratégie, le format et son budget, les contextes et les versions de prompts. Les suppressions de documents suppriment aussi ces caches. Une réutilisation est indiquée dans l'interface et compte zéro appel et zéro token calculé ; le modèle doit toujours être installé et validé.

Le format court demande 70 mots et réserve 256 tokens ; les points clés demandent 120 mots et réservent 384 tokens. Les autres formats réservent 640 tokens et demandent au plus 200 mots. Le budget des sources tient compte de cette réserve avant la génération. Les métriques séparent désormais chargement (`load_ms`), lecture du prompt (`prompt_evaluation_ms`) et génération de sortie (`output_generation_ms`).

L'arrêt de préparation est coopératif entre les événements du flux : un modèle qui ne renvoie rien peut retarder l'arrêt jusqu'au prochain événement ou timeout. Les lots terminés restent en base. Après redémarrage, relancer Préparer recalcule uniquement les lots manquants. L'importation interrompue est transactionnelle et recommence ; elle n'est pas reprise page par page.

## Fidélité et portée

La recherche BM25 consulte le texte original, filtre les années explicites et ne génère rien quand elle ne trouve aucun passage. Le lexique français est simple, sans correction sémantique : une reformulation éloignée peut manquer un passage. Une question transversale peut nécessiter la préparation complète, donc plusieurs minutes sur un grand document. La synthèse couvre tous les fragments traités mais peut perdre un détail ; couverture technique ne signifie pas fidélité sémantique prouvée.

Les références physiques viennent de la base, jamais de numéros de page écrits par le LLM. Le modèle doit citer des identifiants de fragments. Une référence absente du contexte est retirée. Les cartes sources ouvrent le texte original et le PDF à sa vraie page. Cela vérifie l'existence d'une source, pas automatiquement l'implication logique de chaque phrase par cette source. Une réponse sans citation est signalée. Les tableaux détectés sont conservés et indexés ; leur extraction n'est pas universelle.

L'historique est persistant par document (100 derniers échanges affichés). Chaque question est recherchée indépendamment ; pour une relance ambiguë, reformuler les noms et le sujet. Les documents DOCX/TXT indiquent des blocs logiques, jamais des pages Word supposées.

## Confidentialité et périmètre

Le client Ollama a une URL fixe sur loopback, ignore les proxies et refuse les redirections. Vérification des modèles installés et des métadonnées `remote_host`/`remote_model` avant génération ; modèles cloud refusés. Si le lanceur démarre Ollama, il ajoute `OLLAMA_NO_CLOUD=1`. Un service Ollama déjà actif garde sa configuration ; l'application refuse néanmoins les modèles distants.

Aucune police distante, aucun CDN, aucun exporteur de télémétrie ; télémétrie native FastAPI explicitement désactivée. Les liens et images Markdown générés ne déclenchent aucune requête. CSP restrictive, hôtes limités et origines externes refusées. Le contenu des documents est encadré comme donnée non fiable ; le LLM n'a aucun outil, accès shell ou navigateur. Ces mesures réduisent l'injection de prompt, elles ne prouvent pas l'absence d'erreurs sémantiques.

Les fichiers et échanges restent en clair sur le disque de l'utilisateur. Le service n'a pas de compte ni d'authentification : il est destiné à une machine personnelle, lié au loopback. Les autres logiciels locaux de cette session peuvent y accéder. Les installations de dépendances exigent Internet la première fois, contrairement au fonctionnement de l'application une fois installée. Les mises à jour sont manuelles.

## Limites à valider sur documents réels

- OCR local à ajouter ; pas de traduction d'images en texte actuellement.
- Tableaux complexes, titres sans styles et DOCX avec pagination de mise en page.
- Aucune garantie générale contre les hallucinations d'un petit modèle.
- Génération hiérarchique sur 3000 pages réelles non validée : coût potentiellement important, nombreux appels CPU.
- DOCX charge son arbre XML : limite décompressée de 80 Mo, sans promesse de mémoire constante pour ce format.
