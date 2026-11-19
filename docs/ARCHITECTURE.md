# Architecture actuelle de Clair

Relecture du **18 novembre 2026**, fondée sur le code local. Pour une explication simple : [fonctionnement](FONCTIONNEMENT.md). L'[ancienne description](historique/ARCHITECTURE_2026-11-17.md) accompagne les rapports historiques.

## Organisation générale

React/TypeScript affiche l'interface. FastAPI sert l'interface et les routes `/api` sur `127.0.0.1:8765`. SQLite conserve texte, index, synthèses et historique. La génération dans Clair passe exclusivement par WebNN dans Edge. Le code Ollama est réservé aux scripts de comparaison historiques.

Le moteur Python prépare les passages et demande la génération au navigateur dans le flux de réponse. Le worker Edge utilise ONNX Runtime Web. Le même réglage matériel sert aux questions, résumés, préparations et traductions. Automatique : NPU → GPU → CPU ; GPU prioritaire : GPU → NPU → CPU ; NPU prioritaire : NPU → GPU → CPU ; CPU uniquement : CPU. Chaque modèle utilise son tokenizer et son contexte. Qwen3 4B utilise 3 072 tokens et les deux modèles plus légers utilisent 2 048 tokens. Python valide la structure et les identifiants des citations. Les clés de cache incluent le modèle et sa version.

Le worker crée réellement le contexte via `navigator.ml.createContext({deviceType})`, compile les deux sessions ONNX, puis vérifie la génération des nombres 1 à 10 avant de valider un accélérateur. Un échec entraîne sa fermeture et l'essai du périphérique suivant. Chaque tentative d'accélérateur est limitée à 120 secondes ; le budget global reste inférieur aux 900 secondes du serveur. Les échecs sont mémorisés dans `sessionStorage` par profil et contexte, et peuvent être réinitialisés dans les paramètres. Le worker est réutilisé pour les blocs suivants sur le contexte retenu.

Les métriques conservent `device_preference`, `device`, `device_attempts`, `accelerator_check_ms`, `dispatches` et `device_verification`. `hardware_identity_verified` reste faux : une demande `deviceType` et des exécutions WebNN ne suffisent pas à établir l'identité de la puce ou la répartition intégrale des opérateurs. Les métriques restent liées à chaque appel ; une réponse en cache n'est pas une nouvelle exécution. Le cache des réponses distingue les quatre préférences. Les synthèses et les traductions terminées restent réutilisables pour éviter leur recalcul.

Le choix CPU/GPU/NPU correspond aux options de la version d'ONNX Runtime Web intégrée ([référence ONNX Runtime](https://onnxruntime.ai/docs/api/js/interfaces/InferenceSession.WebNNContextOptions.html)). L'[API WebNN reste en évolution](https://www.w3.org/TR/webnn/#dictdef-mlcontextoptions) : la disponibilité d'un contexte et la compatibilité d'un modèle doivent être testées dans le navigateur utilisé.

La recherche utilise SQLite FTS5 et son classement BM25. Il n'y a ni embeddings, ni base vectorielle, ni recherche Web. Le modèle reçoit du texte ; aucun outil shell ou navigateur ne lui est exposé.

| Fichier | Responsabilité |
| --- | --- |
| [main.py](../app/main.py) | Routes HTTP, import, verrou de calcul, préparation, événements de réponse et consultation des sources. |
| [extract.py](../app/extract.py) | Extraction PDF/DOCX/TXT, titres, fragmentation et conservation des pages. |
| [store.py](../app/store.py) | SQLite, documents, fragments et sources. |
| [engine.py](../app/engine.py) | Routage, BM25, contexte, cache des réponses, validation et ancienne hiérarchie compatible. |
| [selection.py](../app/selection.py) | Sélection extractive du rapide, sans LLM, et couverture des passages. |
| [summary.py](../app/summary.py) | Hiérarchie utilisant le budget de tokens Qwen 3.5 et caches intermédiaires. |
| [token_budget.py](../app/token_budget.py) | Compteur BPE issu du vocabulaire GGUF installé ; borne en octets pour les autres cas. |
| [llm.py](../app/llm.py) | Validation du modèle, prompts, appel Ollama, flux et métriques natives. |
| [config.py](../app/config.py) | Contextes, limites de fichiers, threads et maintien des poids en mémoire. |
| [translation.py](../app/translation.py) | Parcours intégral du texte extrait, traduction par blocs, reprise persistante et export DOCX. |
| [TranslationPanel.tsx](../web/src/TranslationPanel.tsx) | Langue cible, progression, arrêt, reprise et téléchargement de la traduction. |
| [main.tsx](../web/src/main.tsx) | Bibliothèque, conversation, choix du mode, progression, couverture et sources. |

## Traduction locale ajoutée le 19 novembre 2026

`POST /api/documents/{doc}/translate` partage le verrou de calcul et le transport NDJSON/WebNN des questions. La traduction utilise son propre prompt, sans consigne de réponse française ni limite de résumé à 200 mots. L'interface transmet le réglage matériel commun et traite les mêmes événements de génération que le chat. Les langues cibles sont validées par l'API ; la langue d'origine est laissée à la détection du modèle.

`translation.py` parcourt `pages.text` dans l'ordre, plutôt que les fragments sélectionnés ou les synthèses. Le tokenizer local découpe les pages en blocs courts, en conservant les caractères et les titres reconnus. Le budget réserve le framing ChatML et jusqu'à 1 024 tokens de sortie dans le contexte du modèle. Une sortie vide ou tronquée entraîne un découpage persistant du bloc, avec une limite de cinq subdivisions ; un échec persistant arrête le traitement.

`translations` conserve la langue, le modèle, les avertissements et l'état ; `translation_blocks` conserve l'ordre, le repère source, le texte d'origine, la traduction et les métriques de chaque bloc réussi. La clé dépend du document, de la langue cible, du profil/version du modèle, du contexte et de la version du prompt. Les blocs réussis sont réutilisés à la reprise. Une interruption marque la traduction en pause ; les travaux restés actifs après un arrêt brutal sont remis en pause à l'initialisation. La suppression d'un document supprime aussi ses traductions par clés étrangères.

`GET /api/documents/{doc}/translations` liste les langues et les traductions enregistrées. `GET /api/documents/{doc}/translations/{id}/download` vérifie l'appartenance au document et refuse un traitement incomplet. L'export DOCX est produit en mémoire avec python-docx, déjà installé, avec des repères de pages ou de blocs. Il ne reconstruit ni les images ni la disposition des tableaux. La complétude du parcours n'est pas un contrôle sémantique de fidélité.

## Import et extraction

Le serveur lit le fichier par blocs, contrôle taille et signature, puis calcule un SHA-256. Le nom de stockage est interne. L'identifiant du document dépend de l'empreinte et de la version de l'extracteur (`extract-v4`). Un import identique déjà terminé réutilise son extraction.

Pour les PDF, PyMuPDF extrait les pages, récupère le sommaire lorsqu'il existe et essaie de détecter les tableaux. Leur texte est ajouté au texte interrogeable. Des règles textuelles repèrent aussi les titres : une ligne en capitales peut devenir une section, et un titre sur plusieurs lignes peut produire plusieurs sections.

Les fragments sont bornés à **1 100 octets UTF-8** et se terminent aussi aux changements de page ou de titre. Dans le PDF de référence, 111 pages produisent 299 fragments et 105 sections détectées. Ce ne sont pas des nombres de chapitres ou d'appels LLM.

DOCX conserve paragraphes, titres et tableaux dans l'ordre, avec des blocs logiques. TXT est lu en UTF-8 et réparti en blocs logiques. Aucune pagination Word n'est inventée. DOCX charge un arbre XML avec une limite de taille décompressée ; aucune mémoire constante n'est garantie pour ce format.

Les images ne sont pas interprétées et l'OCR n'est pas implémenté. La détection de scan repose notamment sur la quantité de texte et la présence d'images ; un pied de page peut empêcher la reconnaissance d'une page essentiellement scannée.

## Routage des demandes

Le mode automatique examine les mentions de chapitre/section/partie, puis les mots de comparaison, puis ceux de synthèse ; sinon il utilise BM25. La route de synthèse devient `fast`. Une demande de risques ou de décisions utilise donc souvent le rapide. Ce sont des règles de mots-clés, pas une classification sémantique générale.

| Stratégie API | Traitement |
| --- | --- |
| `auto` | Choisit selon les règles ci-dessus. |
| `fast` | Tout le texte s'il tient dans le budget, sinon sélection extractive ; un appel final lorsqu'un contexte exploitable est disponible, zéro si la réponse est en cache. |
| `summary` | Hiérarchie sur tous les fragments, puis rédaction finale. |
| `hybrid` | Synthèse hiérarchique et ajout de passages BM25 dans la place restante. Une très petite entrée en mode automatique peut passer en lecture directe. |
| `bm25` | Passages originaux retrouvés par mots, limités au budget. Les années explicites filtrent les résultats. |
| `direct` | Tous les fragments doivent tenir ; refus d'une lecture directe silencieusement partielle. |
| `section` | Section détectée par son titre ; ancien chemin de condensation si elle dépasse le budget. |

**Préparer les synthèses** lance le travail approfondi. Il n'est pas nécessaire pour le rapide ou une question factuelle.

## Sélection rapide

Version `extractive-sections-v1`. Les fragments contigus d'une même section et page sont rassemblés avant la recherche des phrases. Un passage garde les identifiants de tous les fragments qu'il traverse.

Si tout le texte tient, il est transmis intégralement. Sinon, le sélecteur :

1. Écarte les pages de sommaire détectées par leurs lignes à points.
2. Écarte aussi des candidats trop pauvres, des lignes à points et des passages de plus de 2 200 caractères.
3. Classe les passages selon leurs termes informatifs et leur longueur ; pénalise la ressemblance avec ceux déjà retenus.
4. Répartit d'abord une partie du budget sur les pages, annexes comprises, puis cherche une répartition entre sections et complète la place disponible.
5. Vérifie le coût du contexte assemblé.

Ce classement lexical ne comprend pas les contradictions et ne garantit pas de conserver une réserve. La détection des chapitres pour le rapport de couverture reste heuristique. La couverture décrit les passages fournis au modèle, pas les faits restitués.

## Hiérarchie approfondie et compatibilité

Clair utilise `summary.prepare` (`hierarchy-token-v1`) et le tokenizer du modèle WebNN. L'ancienne hiérarchie de `engine.py` (`hierarchy-v7`) sert aux scripts de comparaison historiques.

Le nouveau chemin regroupe les fragments contigus selon leur coût en tokens. Il réutilise les lots historiques reconnus, même si une partie seulement du document est en cache. Les fragments manquants sont regroupés dans les intervalles restants ; tout ancien lot d'une autre version n'est pas nécessairement réutilisable.

Chaque lot donne une note JSON contenant `summary` et `source_ids`. Les notes visent 70 mots ; la synthèse racine vise 160 mots. Au plus six sources représentatives sont demandées par note. Tous les identifiants des fragments traités sont conservés séparément pour suivre la couverture : cette liste est plus large que celle des sources citées dans la note.

Si les notes ne tiennent pas ensemble, elles sont regroupées à leur tour. Arrêt si la taille ne diminue plus ou après douze niveaux. Une sortie tronquée peut être retentée une fois avec une consigne de 40 mots. Un lot tronqué ou structurellement invalide n'est pas mis en cache.

Dans l'essai Ollama historique de 111 pages sans cache, il a fallu quatre lots de lecture, une synthèse globale et une réponse finale. Le nombre de lots dépend du budget disponible.

## Contextes et sorties

Les modèles WebNN utilisent leur contexte fixe pour toutes les stratégies. Le tokenizer local mesure le coût des passages sélectionnés. Le budget réserve de la place pour les consignes et la sortie.

Les scripts de comparaison Ollama historiques utilisent ces réglages de contexte.

| Étape | Contexte utilisé |
| --- | --- |
| Réponse factuelle, lecture directe, section et réponse finale approfondie/hybride | `LOCALDOC_CONTEXT`, 4 096 par défaut. |
| Sélection et rédaction rapides | `min(max(LOCALDOC_CONTEXT, LOCALDOC_SUMMARY_CONTEXT), 8192)`. |
| Nouveaux lots et regroupements Qwen 3.5 | `max(LOCALDOC_CONTEXT, LOCALDOC_SUMMARY_CONTEXT)`. |
| Ancien chemin | Lecture initiale avec `LOCALDOC_CONTEXT` ; regroupements avec le maximum des deux contextes. |

Le défaut de `LOCALDOC_SUMMARY_CONTEXT` est 16 384 si la RAM totale atteint 32 Gio et la RAM disponible 16 Gio au démarrage du processus ; sinon 4 096. Les variables permettent d'autres valeurs dans les bornes de `config.py`. Ce choix selon la RAM ne constitue pas une mesure de vitesse sur le poste cible.

Le compteur Qwen 3.5 est construit en mémoire à partir des tokens et fusions du GGUF renvoyés par `/api/show` local. Aucun tokenizer n'est téléchargé. Le budget réserve consignes, dialogue et sortie. **Les chemins directs, BM25 et section conservent encore des budgets prudents en octets dans `engine.py`** : le compteur BPE n'a pas remplacé tous les budgets historiques.

| Sortie | Plafond de génération |
| --- | ---: |
| Réponse courte | 256 tokens |
| Points clés | 384 tokens |
| Réponse détaillée ou résumé structuré | 640 tokens |
| Nouveau lot intermédiaire | 384 tokens |
| Nouvelle synthèse racine | 640 tokens |

Les réponses rapides/approfondies/hybrides utilisent un JSON final avec au plus 2, 4 ou 5 paragraphes selon le plafond. Les consignes visent respectivement 70, 100 ou 150 mots au total. Les autres réponses utilisent les consignes générales du format, dont 120 mots pour les points clés et 200 pour les formats longs. Ce sont des consignes, pas des longueurs garanties. L'ancien chemin conserve ses réserves et tentatives propres pour la compatibilité.

## Génération et affichage

Un verrou applicatif empêche deux calculs IA simultanés. Le serveur remet les requêtes de génération au worker WebNN dans le flux HTTP. Le navigateur lui renvoie le texte et les mesures via une route locale.

Le serveur émet `status`, `token`, `done` et `error`. Pour le JSON structuré, le modèle peut générer alors que l'utilisateur voit encore l'indicateur de rédaction : la réponse est assemblée et ses références structurées vérifiées avant affichage. Le premier token du modèle et le premier texte visible sont deux mesures différentes.

L'arrêt du calcul annule la requête et interrompt le worker WebNN. Les lots terminés restent disponibles. Un import interrompu recommence son extraction depuis le début.

## Stockage et caches

Le répertoire est `data/` par défaut, configurable par `LOCALDOC_DATA`. Fichiers et échanges sont conservés en clair sur le disque.

| Table ou emplacement | Contenu |
| --- | --- |
| `files/`, `documents` | Fichiers importés et métadonnées. |
| `pages`, `sections`, `chunks` | Texte original extrait, tableaux, structure et fragments liés aux pages. |
| `search` | Index FTS5 pour BM25. |
| `summaries` | Notes et synthèses validées structurellement. |
| `summary_roots` | Raccourci vers une synthèse globale compatible terminée. |
| `answer_cache` | Réponse terminée, sources, avertissements et métriques. |
| `messages` | Historique par document ; cent derniers échanges chargés dans l'interface. |
| `llm_calls` | Appels instrumentés, identifiant d'exécution et métriques natives. |

Les clés de synthèse incluent contenu, références, digest des poids, version du prompt, contexte et threads. Les réponses utilisent `answer-v4` et dépendent aussi de la question exacte, du format, de la stratégie et du contenu des fragments. Les caches sont liés au document importé ; il n'existe pas de réutilisation entre deux versions de fichier avec remappage automatique des citations.

Une réponse finale n'est réutilisable que si elle se termine normalement avec des citations autorisées. La réutilisation conserve sources et avertissements, signale `cached_answer` et compte zéro appel et zéro token pour cette demande. Le modèle reste validé avant cette réutilisation. Supprimer un document supprime ses données liées ; arrêter l'application conserve les données.

## Mesures et références

Le worker WebNN mesure le chargement, la lecture du contexte et la rédaction. Il transmet les tokens, la raison de fin et le nombre d'exécutions déléguées à WebNN. Un identifiant d'exécution relie les appels d'une demande. Les totaux incluent les essais terminés ou tronqués dont les mesures ont été reçues.

`calls` décrit chaque appel et `total_ms` mesure la demande complète, préparation locale comprise. Le [guide des mesures](OPTIMISATION.md) détaille les anciens essais Ollama.

Les pages des cartes proviennent de SQLite. Une référence non autorisée est retirée ou provoque le rejet d'une sortie structurée. Cela ne vérifie pas l'implication logique d'une phrase par sa source. Voir les erreurs observées dans [VALIDATION.md](VALIDATION.md).

## Confidentialité et déploiement

Le navigateur récupère le modèle et ses dépendances depuis le serveur Clair local. Le téléchargement initial des fichiers du modèle et des dépendances s'effectue pendant l'installation.

L'interface n'utilise ni CDN ni police distante. Les liens et images Markdown générés ne déclenchent pas de chargement externe. Le document est présenté comme une donnée non fiable et le modèle n'a aucun outil. Ces protections ne prouvent pas l'absence d'injection ou d'erreur de sens et ne remplacent pas un audit réseau de tous les logiciels du poste.

Le service est lié au loopback, sans compte ni authentification : il vise un usage personnel local. Les autres logiciels de la session peuvent y accéder. OCR, compréhension d'images, fidélité générale et analyse IA complète de milliers de pages réelles ne sont pas validés.
