# Optimisation actuelle du moteur de résumé

État relu le **18 novembre 2026**. Ce document explique ce qui accélère le moteur et comment lire les chiffres. Voir [le fonctionnement simple](FONCTIONNEMENT.md) et [le diagnostic détaillé](RESUME_RAPIDE.md).

## Le problème initial

L'extraction du PDF de 111 pages prenait environ 8,245 secondes. Le coût principal venait des appels au modèle : un ancien plan comportait 135 lots de lecture, auxquels s'ajoutaient les regroupements et la réponse finale.

L'ancien budget comptait chaque octet UTF-8 comme un token. Cette borne prudente laissait peu de place au texte français dans chaque lot. Les petites sections et les titres fragmentés augmentaient aussi le nombre de lots. Changer uniquement le parseur PDF n'aurait pas supprimé ces générations successives.

Les métriques natives complètes de l'ancienne session d'une heure n'ont pas été conservées. Le nombre exact de ses tentatives et ses tokens totaux ne peuvent pas être reconstitués honnêtement.

## Les changements en place

| Changement | Coût réduit | Limite |
| --- | --- | --- |
| Rapide : sélection extractive avant un seul appel | Nombre de générations et volume transmis au modèle. | Des informations et réserves peuvent être omises. |
| Compteur BPE local Qwen 3.5 | Surestimation du budget dans les nouveaux chemins de résumé. | Certains chemins conservent les budgets historiques en octets. |
| Approfondi : lots selon les tokens disponibles | Multiplication des petits lots. | La condensation successive peut perdre du sens. |
| Notes intermédiaires courtes et structurées | Volume de texte à générer et à relire. | Une note courte ne conserve pas tous les détails. |
| Caches de lots, de synthèse racine et de réponse | Recalcul d'un résultat compatible déjà terminé. | Le cache ne vérifie pas de nouveau son contenu. |
| `keep_alive: 10m` | Rechargement des poids entre demandes rapprochées. | Ne réduit pas le calcul des tokens. |
| Journal par appel et totaux | Erreurs de diagnostic sur le coût réel. | Un appel interrompu peut ne pas retourner ses comptes natifs. |

Le moteur reste sur CPU, avec au plus huit threads et un calcul actif dans l'application. Aucun parallélisme supplémentaire n'a été activé pour obtenir les chiffres ci-dessous. Thinking était déjà demandé désactivé ; ce n'est pas l'origine principale du gain.

## Gain effectivement mesuré

Même PDF, même Qwen 3.5 9B Q4_K_M, caches applicatifs vides, modèle préchargé, texte déjà extrait, PC de développement :

| Mode | Durée | Appels | Tokens d'entrée | Tokens de sortie |
| --- | ---: | ---: | ---: | ---: |
| Rapide final | **243,294 s** | **1** | 7 098 | 564 |
| Approfondi optimisé | **1 101,443 s** | **6** | 48 539 | 1 551 |
| Répétition exacte | Environ 0,30 s | 0 | 0 | 0 |

Le facteur d'accélération est `1101,443 / 243,294 = 4,527`. Le temps diminue de `1 - 243,294 / 1101,443 = 77,911 %`. Les tokens d'entrée diminuent de 85,377 % et ceux de sortie de 63,636 %.

Ces valeurs ne sont pas un facteur garanti pour tous les documents. Un seul essai est retenu par mode et les débits de la machine ont varié. La comparaison avec l'heure signalée avant optimisation serait indicative, car elle ne dispose pas du même protocole ni de métriques historiques complètes.

Le premier rapide d'essai, en 181,837 s, utilisait une consigne antérieure. Il reste dans `superseded_runs` et est exclu du gain final. Le [rapport brut](benchmark-summary-modes.json) conserve les réponses et les métriques qui permettent de vérifier le calcul.

## Lire les mesures sans les confondre

| Champ | Sens |
| --- | --- |
| `total_ms` | Temps total de la demande dans le moteur. Le rapport ajoute `wall_ms`, mesuré par le script appelant. |
| `model_calls` | Appels du pipeline pour cette demande, tentatives instrumentées comprises. Le préchargement du benchmark est rapporté à part. |
| `prompt_tokens` | Somme des tokens d'entrée retournés par Ollama ; un passage relu à plusieurs niveaux peut compter plusieurs fois. Ce n'est pas le nombre de tokens uniques du PDF. |
| `output_tokens` | Somme des tokens générés par les appels, y compris les générations intermédiaires. |
| `load_ms` | Chargement natif observé, cumulé sur les appels. |
| `prompt_evaluation_ms` | Temps natif de lecture des prompts, cumulé. |
| `output_generation_ms` | Temps natif de génération de sortie, cumulé. |
| `tokens_per_second` | Débit de sortie ; au total, tokens générés divisés par le temps de génération de sortie. |
| `calls` | Détail par appel : comptes, durées, contexte, plafond de sortie, raison de fin et Thinking reçu. |
| `first_token_ms` | Premier token du dernier appel ; il peut s'agir d'un token JSON non encore affiché. |
| `time_to_first_token_ms` | Temps depuis la question jusqu'au premier token de la rédaction finale. |
| `time_to_first_visible_token_ms` | Temps jusqu'au premier texte envoyé pour affichage, distinct du premier token brut lorsque le JSON est assemblé. |
| `cached_answer` | Réponse terminée réutilisée ; zéro appel et zéro token pour la nouvelle demande. |
| `coverage` | Sections et pages fournies, puis pages citées ; pas une validation du sens de chaque affirmation. |

La référence mesurée est le compte natif d'Ollama, pas le budget du tokenizer. La somme des durées natives ne remplace pas le temps total : préparation locale, requêtes et validation ajoutent un coût. Sur un appel interrompu sans événement final, le journal conserve l'appel mais laisse ses tokens inconnus ; un zéro de réutilisation en cache a un sens différent.

## Pourquoi conserver deux modes

Le rapide réduit le volume à traiter et convient à une première lecture accompagnée d'une vérification des sources. L'approfondi parcourt tous les fragments extraits et garde les résultats intermédiaires pour les questions suivantes. Son coût supérieur ne garantit pas une meilleure fidélité.

La revue du PDF a relevé des erreurs dans les deux modes, notamment sur le statut de conformité RGAA et des hypothèses transformées en faits. Les détails sont dans [la validation actuelle](VALIDATION.md). Il serait incorrect de présenter le gain de temps comme une preuve d'exhaustivité ou de qualité automatiquement conservée.

## Réglages et réglages non modifiés

Les contextes, plafonds de sortie et chemins de compatibilité sont décrits dans [l'architecture](ARCHITECTURE.md). Sur le test : rapide 8 192, préparation approfondie 16 384, réponse finale approfondie 4 096. Le réglage de contexte doit laisser de la place à la réponse ; la taille maximale annoncée par un modèle n'est pas une recommandation pour un CPU.

Le modèle n'a pas été remplacé, le GPU n'a pas été activé et l'interface comme le backend conservent leur architecture. Aucun gain sur un autre poste n'est déduit de cet essai.

## Historique et reproduction

Les essais du 17 novembre sur la brièveté des réponses, le cache et le prompt compact restent dans [l'historique des optimisations](historique/OPTIMISATION_2026-11-17.md). Ils utilisent surtout le petit document Horizon ; ils ne sont pas la mesure actuelle du PDF de 111 pages.

Le protocole de reproduction, les prérequis et le suivi du benchmark figurent dans [VALIDATION.md](VALIDATION.md#reproduire-sans-confondre-les-essais).
