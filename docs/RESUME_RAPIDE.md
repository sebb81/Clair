# Résumé rapide et diagnostic CPU — 18 novembre 2026

Rapport daté des essais du 18 novembre, conservé comme preuve. Pour une explication simple, lire [FONCTIONNEMENT.md](FONCTIONNEMENT.md) ; pour distinguer documents actuels et archives, consulter [l'index](README.md). Les comptes de cache ci-dessous décrivent l'instant du diagnostic, pas un état permanent de la bibliothèque.

Le moteur existant est conservé : FastAPI, React, SQLite et Ollama. La stratégie automatique route les demandes de résumé vers `fast`. `summary` reste le mode approfondi ; le bouton « Préparer les synthèses » prépare ce dernier. L'interface existante reçoit une option et un détail de couverture.

## Diagnostic du PDF local de 111 pages

- Document : `30a5b4ef7fb945d5eb37a401`. Extraction déjà enregistrée : **8,245 s**, 182 372 octets de texte avant fragmentation.
- **299 fragments**, entre 2 et 1 099 octets, totalisant 177 172 octets après nettoyage. Ce sont des fragments de pages et de titres, pas 299 pages. L'extracteur limite chaque fragment à 1 100 octets et termine les fragments aux pages et aux changements de section.
- **105 sections détectées**, dont des lignes du sommaire et des titres coupés sur plusieurs lignes. Ce sommaire automatique ne constitue pas une liste fiable de 105 chapitres.
- Le budget historique de lecture est **2 062 octets** pour un contexte annoncé de 4 096 tokens : l'ancienne fonction compte chaque octet UTF-8 comme un token et réserve le prompt canonique long. Elle surestime nettement le texte français.
- Les **135 lots** sont le plan de lecture regroupé, pas le nombre de pages ni de fragments. Le découpage strict par sections produirait 192 lots. Lors du diagnostic, le cache local contenait 135 synthèses de niveau 2 et une synthèse de niveau 3, sans synthèse racine complète compatible.
- Les 135 synthèses de lecture conservées totalisent **2 389,74 s** (39 min 49,74 s) de génération enregistrée. Le parent conservé ajoute 97,93 s. Ces lignes prouvent des calculs terminés, pas le nombre exact d'appels d'une session ancienne : des tentatives tronquées et des versions précédentes peuvent manquer.
- Les tokens et temps de **chaque** ancien appel n'ont pas été conservés. Les reconstituer exactement serait inventer des mesures. Les anciens messages cumulaient le nombre d'appels mais n'affichaient que les tokens du dernier. La nouvelle instrumentation conserve chaque appel, les tentatives, les totaux et les interruptions sans métriques finales.
- Cache : extraction par empreinte du fichier ; synthèses par contenu, modèle et paramètres ; réponse finale par document, question, stratégie, format et paramètres. Le nouveau moteur réutilise aussi les lots anciens reconnus, même si seule une partie du plan est en cache. Il n'implémente pas de réutilisation entre deux imports différents avec remappage de citations.

## Modèle et paramètres vérifiés

Ollama local **0.40.16**, modèle **qwen3.5:9b**, famille `qwen35`, **9,0 milliards** de paramètres, quantification **Q4_K_M**, empreinte `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`. Le modèle déclare un contexte maximal de 262 144 tokens ; cela ne signifie pas que cette taille soit adaptée au CPU.

Sur ce PC de développement (environ 64 Gio de RAM) : contexte questions 4 096, rapide 8 192, approfondi 16 384. Sur une machine avec moins de RAM disponible, le défaut reste 4 096. Les valeurs effectives de `/api/ps` figurent dans le rapport brut. Le processus réel `llama-server.exe` utilise `-ngl 0`, `-t 8`, `-np 1` ; `/api/ps` confirme zéro VRAM. Aucun parallélisme supplémentaire n'est activé.

`think: false` était déjà présent ; `/api/show` annonce que cette valeur est acceptée, bien que le défaut du modèle soit Thinking activé. Les nouveaux appels mesurent les caractères `message.thinking` reçus. `num_predict` vaut 384 pour les nouveaux lots intermédiaires, 640 pour la synthèse racine et la réponse détaillée finale (256 en réponse courte, 384 en points clés). `keep_alive` passe à `10m`, réglable par `LOCALDOC_KEEP_ALIVE` : cela évite des rechargements entre demandes rapprochées, sans accélérer le calcul des tokens lui-même.

Le tokenizer BPE est construit en mémoire à partir des tokens et fusions GGUF renvoyés par **Ollama local**. La présegmentation suit le tokenizer Qwen 3.5. Une réserve de dialogue et de sortie s'ajoute aux comptes de texte ; `prompt_eval_count` reste la mesure native de référence. Les autres modèles gardent le budget prudent en octets. Le tokenizer ne télécharge aucun poids ou vocabulaire.

## Fonctionnement et limites

**Rapide :** rassemble les fragments contigus par section et page, retrouve les phrases, conserve tous les identifiants des fragments traversés, exclut les pages de sommaire détectées, classe les passages par termes informatifs et pénalise la redondance. Une sélection répartie sur les pages précède la couverture des sections ; les annexes restent donc éligibles même lorsqu'elles appartiennent à une seule section. Le nombre de passages dépend du budget de tokens. Un seul appel produit les paragraphes et leurs sources dans un schéma JSON validé. Aucun appel de correction automatique ne se cache derrière ce mode. Une sortie tronquée ou sans sources valides ne devient pas un résultat en cache.

La couverture affichée décrit les **passages fournis au modèle**. Elle ne garantit pas que chaque passage ait contribué au texte final. Le rapport distingue pages sélectionnées, sections sélectionnées et pages citées. Les images, captures de code dans les images et scans non reconnus ne sont pas lus. Les citations ont des identifiants réels et des pages fournies par l'application ; leur existence ne prouve pas que chaque affirmation soit justifiée.

**Approfondi :** regroupe les fragments contigus selon leur coût BPE, avec une réserve de sortie ; condensation courte structurée et cache à chaque niveau ; réduction hiérarchique seulement tant que les notes ne tiennent pas ensemble. Tous les identifiants des blocs lus restent suivis, mais les notes et le résumé final peuvent perdre des détails. Le coût et les tentatives sont conservés, y compris lorsqu'une tentative tronquée est suivie d'une seconde plus concise.

## Protocole et résultats

Les résultats, compteurs natifs par appel et résumés complets se trouvent dans [`benchmark-summary-modes.json`](benchmark-summary-modes.json).

| Stratégie, caches applicatifs vides | Durée totale | Appels du pipeline | Tokens d'entrée cumulés | Tokens de sortie cumulés |
| --- | ---: | ---: | ---: | ---: |
| Rapide, version finale | **243,294 s (4 min 03 s)** | **1** | **7 098** | **564** |
| Approfondi optimisé | **1 101,443 s (18 min 21 s)** | **6** | **48 539** | **1 551** |
| Répétition rapide en cache | 0,304 s | 0 | 0 | 0 |
| Répétition approfondie en cache | 0,301 s | 0 | 0 | 0 |

**Gain mesuré : 4,527×, soit 77,911 % de temps en moins.** Les tokens d'entrée diminuent de 85,377 %, les tokens de sortie de 63,636 % et les appels du pipeline de 83,333 %. Ces chiffres comparent les deux stratégies nouvelles ; ils ne reconstituent pas une ancienne session d'une heure. Par rapport à l'heure signalée, le rapport arithmétique serait environ 14,8×, mais ce n'est pas une comparaison contrôlée avec les métriques historiques.

Le rapide fournit 77 passages représentant 80 identifiants de fragments, sur 62 pages et 50 des 105 sections détectées. Son contexte contient des passages des **4 chapitres**. Les pages de sommaire détectées (2 à 8) sont exclues. Le résumé final cite 15 identifiants sur 12 pages ; il ne restitue pas distinctement les quatre chapitres. L'approfondi lit les 299 fragments, sur les 111 pages enregistrées, mais sa réponse finale ne cite que six identifiants sur cinq pages. Ces deux mesures de couverture ne sont pas équivalentes.

### Temps de chaque appel approfondi

| Appel | Entrée | Sortie | Durée mesurée par le client Ollama |
| --- | ---: | ---: | ---: |
| Lecture 1 | 14 571 | 153 | 272,520 s |
| Lecture 2 | 14 779 | 205 | 288,001 s |
| Lecture 3 | 14 699 | 160 | 301,125 s |
| Lecture 4 | 3 016 | 185 | 87,640 s |
| Synthèse globale | 890 | 403 | 71,588 s |
| Rédaction finale | 584 | 445 | 79,812 s |

Le seul appel rapide prend 242,495 s : 154,237 s de lecture du prompt et 88,144 s de génération native, soit 46,02 tokens d'entrée/s et 6,40 tokens de sortie/s. Les autres frais du pipeline représentent environ 0,8 s. Les six appels approfondis retournent tous `done_reason: stop`, sans nouvelle tentative, et aucun caractère Thinking n'est reçu dans les deux modes.

Le préchargement hors chronomètre a nécessité un appel supplémentaire par stratégie (159 tokens d'entrée, 6 de sortie) : 8,923 s pour le rapide, dont 4,732 s de chargement ; 7,044 s pour l'approfondi, dont 3,935 s de chargement. Les appels de déchargement `keep_alive: 0` ne génèrent pas de texte. Dans le pipeline rapide mesuré, le chargement natif n'est ensuite que de 26,8 ms.

La version finale rapide a été mesurée après l'approfondi. Un premier essai rapide, avant renforcement des consignes de qualification, prenait 181,837 s ; il reste dans `superseded_runs` et n'est pas utilisé pour calculer le gain final. Les débits observés varient entre essais : le préchargement final rapide lisait environ 45 tokens/s, contre environ 63 lors du préchargement approfondi. L'ordre des essais et la charge de la machine ne sont donc pas neutralisés par un protocole statistique ; le facteur 4,527× décrit cet essai.

### Qualité : validation partiellement négative

Le rapide conserve le projet WordPress/MyListing, la messagerie JavaScript/PHP, la logique d'abonnements et les risques CSRF/SQL. Il garde aussi certaines réserves : des activités restent proposées et l'architecture complète en trois couches n'est pas encore réalisée (pages 37 et 43, S156/S174).

**Il reste des erreurs significatives, malgré la consigne renforcée et les références structurées :**

- Le rapide affirme un respect du RGAA. La page 81 (S278/S280) précise que les ratios de contraste n'ont pas été conservés et que le contrôle ne démontre pas la conformité. Cette réserve n'était pas dans la sélection finale. La page 32 (S139) décrit des recommandations suivies, pas une conformité démontrée.
- Le rapide présente des contraintes SQL comme réalisées, alors que la page 36 (S151/S152) distingue les contrôles applicatifs réellement employés d'une architecture SQL envisagée.
- L'approfondi transforme l'hypothèse de 500 utilisateurs (page 31, S134) en capacité effective et la conformité non démontrée en non-conformité (page 81). Plusieurs citations finales ne justifient pas les affirmations de leur paragraphe.
- Dans les deux modes, des thèmes ou réserves se perdent. La couverture des chapitres dans l'entrée ne prouve pas leur restitution dans la sortie. Le mode approfondi conserve l'avantage de parcourir tous les blocs, sans garantir une meilleure fidélité sémantique.

**Le gain de performance est validé sur ce PDF et cette machine ; la fidélité sémantique complète ne l'est pas.** Ces résultats conviennent à une première lecture avec vérification des sources, pas à une certification automatique d'exhaustivité ou de conformité. Les avertissements de l'application distinguent sélection partielle, lecture de tous les blocs et validation limitée des références.

Vérification du code : 42 tests Python ciblés passent (test de stress d'extraction de 3 000 pages non relancé, extracteur inchangé), compilation TypeScript/Vite réussie, un parcours Edge réussi avec API simulée pour vérifier options, couverture partielle et cartes de pages. Les durées ci-dessus proviennent du vrai modèle local appelé par le moteur, pas des doubles utilisés dans les tests.

Même PDF, même empreinte, mêmes poids Qwen 9B, CPU, appels séquentiels. Chaque stratégie utilise une copie isolée de SQLite dont seuls les caches copiés sont vidés. Le modèle est déchargé, puis préchargé avec un petit prompt avant chaque stratégie : les temps de chargement de ce préchargement sont rapportés séparément. Les répétitions utilisent ensuite le cache applicatif. Une seule mesure par stratégie ne démontre pas une distribution de latence. L'extraction déjà faite est exclue des durées de résumé et rapportée séparément.

Il s'agit du **PC de développement**, pas d'un benchmark sur le Dell cible. Le gain face à l'heure signalée par l'utilisateur reste une comparaison indicative ; les deux stratégies nouvellement mesurées constituent la comparaison contrôlée.

Reproduction depuis la racine :

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_summary_modes 30a5b4ef7fb945d5eb37a401
Get-Content data\summary-benchmark-progress.json
```

Les données utilisateur et anciens caches ne sont pas vidés. Les copies de benchmark et leurs journaux d'appels restent dans `data/summary-benchmark-*` pour inspection.

## Références techniques

- [API Ollama officielle : compteurs et durées](https://github.com/ollama/ollama/blob/main/docs/api.md).
- [Configuration officielle du tokenizer Qwen 3.5](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/tokenizer_config.json).
