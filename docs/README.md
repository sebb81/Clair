# Documentation de Clair

Documentation relue le **18 novembre 2026** par comparaison avec le code et les rapports enregistrés. Les mesures gardent leur date d'origine : cette relecture ne constitue pas un nouveau benchmark.

## Par où commencer ?

| Votre besoin | Document |
| --- | --- |
| Expliquer simplement le fonctionnement, avec un exemple et un texte à dire à l'oral | **[Comprendre le fonctionnement](FONCTIONNEMENT.md)** |
| Installer, démarrer et utiliser l'application | [Guide de démarrage](../README.md) |
| Comprendre les modules, les budgets, les caches et les flux | [Architecture actuelle](ARCHITECTURE.md) |
| Expliquer les optimisations et le gain mesuré | [Optimisation actuelle](OPTIMISATION.md) |
| Savoir ce qui a été testé et ce qui reste incertain | [Validation actuelle](VALIDATION.md) |
| Examiner le diagnostic détaillé du PDF de 111 pages | [Rapport de résumé rapide](RESUME_RAPIDE.md) |

Pour une présentation, commencez par `FONCTIONNEMENT.md`. Les JSON servent à justifier les chiffres ; ils ne sont pas le support d'explication principal.

## Trois distinctions à conserver

1. Extraire le texte ne signifie pas que le modèle a lu tout le PDF, ses images et ses tableaux.
2. Fournir des passages de quatre chapitres ne signifie pas que les quatre chapitres sont restitués dans le résumé.
3. Vérifier une référence confirme qu'elle existe, pas qu'elle justifie toutes les affirmations du paragraphe.

Le gain de temps du rapide est mesuré. Des erreurs de sens restent observées dans les deux modes et sont décrites dans la validation.

## Inventaire des résultats et des captures

Les rapports bruts et captures ci-dessous sont conservés sans modification sur le poste d'origine. Ils sont exclus du dépôt public, sauf la capture simulée `summary-fast-coverage.png`, car ils peuvent contenir des extraits de documents personnels ou des informations locales. Les liens vers ces fichiers nécessitent donc une copie locale des résultats. Les scripts de benchmark restent disponibles dans `scripts/` pour produire de nouveaux rapports sur ses propres documents.

Un ancien relevé matériel, un ancien audit ou une ancienne capture reste un document historique, même si le fichier est encore dans ce répertoire.

### Référence du 18 novembre

| Fichier | Contenu et statut |
| --- | --- |
| [benchmark-summary-modes.json](benchmark-summary-modes.json) | Même PDF de 111 pages, vrai Qwen 9B CPU, comparaison rapide/approfondi, répétitions et métriques par appel. Les exécutions retenues sont dans `runs`. `superseded_runs` contient un essai antérieur exclu du gain final. |
| [summary-fast-coverage.png](summary-fast-coverage.png) | Capture du test d'affichage de la couverture avec API simulée ; ce n'est pas un vrai résumé du PDF utilisateur. |

### Mesures historiques du 17 novembre

| Fichier | Périmètre |
| --- | --- |
| [benchmark-optimization.json](benchmark-optimization.json) | Réponse courte et cache sur le petit document Horizon ; ce n'est pas le test de 111 pages. |
| [benchmark-prompt-compression.json](benchmark-prompt-compression.json) | Formulation compacte du prompt ; réduction des tokens sans preuve de gain proportionnel en temps. |

### Mesures historiques du 16 novembre

| Fichier | Périmètre |
| --- | --- |
| [benchmark-qwen3.5-2b.json](benchmark-qwen3.5-2b.json) | Ancien moteur, Qwen 2B, petit PDF Horizon. |
| [benchmark-qwen3.5-9b.json](benchmark-qwen3.5-9b.json) | Ancien moteur, Qwen 9B, petit PDF Horizon. |
| [benchmark-qwen3.5-2b-checks.json](benchmark-qwen3.5-2b-checks.json) | Contrôles du rapport 2B ; pas une évaluation générale de fidélité. |
| [benchmark-qwen3.5-9b-checks.json](benchmark-qwen3.5-9b-checks.json) | Contrôles du rapport 9B, avec la même limite. |
| [benchmark-real.json](benchmark-real.json) | Rapport initial d'exécution réelle du modèle ; distinct de la comparaison actuelle. |
| [benchmark-large.json](benchmark-large.json) | Extraction seule de 3 000 pages synthétiques ; zéro appel LLM. |
| [runtime-snapshot.json](runtime-snapshot.json) | Photographie des processus et de la mémoire à cette date ; pas l'état actuel du PC. |
| [cpu-runner-flags.json](cpu-runner-flags.json) | Arguments d'un ancien processus CPU ; PID et contexte historiques. |
| [dependency-audit.json](dependency-audit.json) | Audit des dépendances de cette révision ; ne couvre pas automatiquement les ajouts ultérieurs. |

### Captures historiques

| Fichier | Date et signification |
| --- | --- |
| [accueil.png](accueil.png) | 17 novembre : écran d'accueil. |
| [sources.png](sources.png) | 17 novembre : consultation d'un passage source. |
| [mobile.png](mobile.png) | 17 novembre : affichage sur un petit écran. |
| [summary-progress.png](summary-progress.png) | 17 novembre : ancien parcours de préparation hiérarchique. |
| [summary-recovery-running.png](summary-recovery-running.png) | 16 novembre : reprise d'une préparation déjà partiellement en cache. |
| [summary-complete.png](summary-complete.png) | 16 novembre : réponse de l'ancien moteur après reprise ; pas une preuve de qualité du mode actuel. |

## Versions précédentes des explications

- [Architecture du 17 novembre](historique/ARCHITECTURE_2026-11-17.md).
- [Validation du 16 novembre](historique/VALIDATION_2026-11-16.md).
- [Optimisations du 17 novembre](historique/OPTIMISATION_2026-11-17.md).

## Maintenir cette documentation

Après une modification du moteur, vérifier ensemble le fonctionnement, l'architecture, l'optimisation, la validation et le guide de démarrage. Toute nouvelle mesure doit préciser sa date, le modèle, le matériel, l'état du cache et le périmètre chronométré. Conserver les anciens résultats avec leur contexte, sans remplacer leur date par celle de la relecture.
