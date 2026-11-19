> Archive : explication de la version indiquée dans le nom du fichier. Pour le fonctionnement actuel, consulter [l’index de la documentation](../README.md). Les liens des illustrations sont adaptés à cet emplacement.

# Mesure du 17 novembre 2026

Essai réel, Qwen 3.5 9B installé, CPU, modèle préchargé, PDF synthétique Horizon de quatre pages. Base isolée temporaire ; aucun document utilisateur modifié. Une seule mesure par cas, dans cet ordre : elle ne démontre ni un gain universel ni la qualité sur de longs documents.

| Cas | Durée totale | Tokens produits | Appels |
| --- | ---: | ---: | ---: |
| Ancienne consigne « réponse courte », plafond 640 tokens | 27,14 s | 189 | 1 |
| Nouvelle consigne 70 mots, plafond 256 tokens | 19,29 s | 119 | 1 |
| Répétition exacte avec réponse en cache | 0,264 s | 0 | 0 |

La seconde réponse conserve l'objectif, le budget, les risques et les décisions, dont le prestataire restant à sélectionner, avec les références des quatre pages. Elle omet des détails présents dans la première ; la concision explique l'essentiel du gain (~29 %). Le débit de génération reste voisin de 10 tokens/s. Le cache renvoie exactement le même texte et les mêmes sources, sans nouvelle vérification sémantique.

Les 32 tests Python passent, dont interruption/reprise, couverture des fragments, invalidation selon le modèle et les options, suppression des caches avec le document et exclusion des réponses tronquées ou aux références invalides. Ces tests fonctionnels utilisent des doubles de modèle ; les temps du tableau proviennent du vrai modèle.

La compilation TypeScript/Vite et les trois parcours Edge passent également : réponse CPU et sources PDF, persistance et affichage mobile, DOCX et information absente, progression et interruption du résumé sur le PDF local de 111 pages. Le serveur a été redémarré avec les changements, en conservant les quatre documents présents avant ce redémarrage.

Rapport brut : `benchmark-optimization.json`. Reproduction : `.\.venv\Scripts\python.exe -m scripts.benchmark_optimization` depuis la racine. Le benchmark charge le modèle 9B local et utilise le CPU ; le lancer hors d'une préparation en cours. Aucune accélération GPU activée ou mesurée. Le premier résumé hiérarchique d'un gros document reste coûteux.

## Compactage du prompt

Second essai réel sur la même fixture et le modèle 9B CPU, avec un plafond de sortie identique entre les versions. Comptes mesurés par Ollama :

| Cas | Entrée canonique | Entrée compacte | Réduction |
| --- | ---: | ---: | ---: |
| Résumé court | 585 tokens | 466 tokens | 20,3 % |
| Lot JSON structuré | 642 tokens | 529 tokens | 17,6 % |

Il s'agit de deux essais ponctuels, pas d'un gain de vitesse établi : le cache de préfixe avantage fortement la lecture du prompt canonique dans le premier cas (0,125 s contre 6,594 s). La sortie compacte courte produit 97 tokens contre 112 ; la sortie JSON en produit 156 contre 136, car le modèle a retenu davantage de faits malgré la suppression des citations répétées. Réduire l'entrée ne garantit donc pas une réduction proportionnelle de la durée totale. Le résumé conserve le budget 2027 mais certaines formulations de statut restent à vérifier dans les sources ; aucun compactage ne garantit la fidélité sémantique du modèle.

Les essais complémentaires retrouvent l'absence de taux de TVA et ne suivent pas une instruction injectée demandant de répondre « PIRATE ». Ils ne constituent pas une preuve générale de résistance aux injections. Les 34 tests Python ciblés passent (test lent d'extraction exclu) : préservation des mots des sources, tableaux et indentation, références des doublons, séparation des faits différents, reprise des caches et contrôles existants. Sur le PDF local de 111 pages, les 135 lots de lecture sont encore retrouvés en cache, sans appel modèle ; une synthèse globale déjà complète n'était pas présente dans cette révision de la base.

Rapport brut : `benchmark-prompt-compression.json`. Reproduction : `.\.venv\Scripts\python.exe -m scripts.benchmark_prompt_compression`. Les originaux et anciens résumés ne sont pas réécrits.
