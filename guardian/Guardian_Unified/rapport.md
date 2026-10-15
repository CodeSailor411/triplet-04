# Rapport de travail — Guardian Reading Inspector

**Date : 15 octobre 2026**  
**Périmètre :** analyse de `PLAYGROUND_FIX_AGENT_PROMPT.md` et mise en œuvre des tâches T1–T7 dans `C:\Users\Dell\Documents\guardian`.

## Résumé

Le testeur React a été remis en cohérence avec les spécifications : il charge les presets Water corrigés, appelle le vrai modèle via un outil MCP local, distingue les trois états d’alerte et l’indisponibilité, explique les signaux, compare un calcul de référence configurable et expose les dix champs d’entrée. Le protocole demeure MCP `2026-07-28`. Aucun score ML n’est présenté comme score de confiance Guardian et aucun jeton d’action n’est produit.

## Changements réalisés

- **Serveur MCP :** ajout de `evaluate_reading_advisory` et `describe_capabilities`; chargement de l’artefact local avec le module feature et la configuration correspondants; seuil, bande d’incertitude, domaines et règles de référence distribués aux clients. Les routes REST de santé/prédiction sont réservées au débogage local.
- **Interface :** presets Normal, Fake flood (180 cm), Smart spoof, Stuck sensor et Adaptive ramp normalisés à la plage du domaine; bouton Custom automatique à l’édition; valeur manquante transmise comme `null`; libellés des états transparents; résultats indisponibles sans probabilité fabriquée; détails complets des dix entrées; panneau « Why » et panneau « Reference rules »; design sombre conservé.
- **Tests :** ajout de tests Python MCP/parité et Playwright; documentation README, carte d’interface et hypothèses mises à jour.
- **Dépendances :** MCP Python SDK `2.0.0`, client MCP JavaScript `2.3.1`, outil Playwright; scikit-learn reste épinglé à `1.7.2` selon l’estimateur sérialisé.

## Vérifications exécutées

- `pytest -q tests` : **6 tests réussis**. La suite comprend 60 entrées aléatoires comparées entre l’appel MCP et l’inférence Python directe à une tolérance `1e-6`; cinq probabilités Water vérifiées dans ±0.02; 25 états pour les quatre autres domaines; entrée mal formée; valeur `null`; champs inconnus; capacités.
- `pnpm run build` : **réussi** avec Vite 8.3.4.
- `pnpm run test:e2e` : **5 tests Playwright réussis** avec Chromium. Vérifiés : sélection des presets et Custom, trois états, valeur null indisponible sans probabilité, clavier, appels externes bloqués, serveur MCP arrêté.
- Le serveur Streamable HTTP a répondu aux appels navigateur en local sur `127.0.0.1:5001`; ses journaux confirment les appels `POST /mcp`.

### Résultats des presets

| Preset Water | P(suspicious) mesurée | État |
|---|---:|---|
| Normal | 0.2090 | Trusted / Below alert threshold |
| Fake flood (T5) | 1.0000 | Suspicious pattern |
| Smart spoof | 0.8110 | Suspicious pattern |
| Stuck sensor | 0.0446 | Trusted / Below alert threshold |
| Adaptive ramp | 0.5513 | Uncertain / Near threshold — ignored by scoring |

Les quatre domaines non-Water gardent les mêmes états pour les presets, sauf **Adaptive ramp en Traffic**, mesuré `Trusted` au lieu de `Uncertain`. Ce résultat est documenté et testé.

## Éléments non réalisés et limites

- Stretch S1 (génération de tendances bénignes, réentraînement, recalcul métriques/seuil) n’a pas été réalisé; le modèle n’a pas été modifié.
- Le dépôt de l’application ne contient pas de `scoring.py` Guardian à raccorder. Le tool MCP est disponible et appelé par le playground, mais son intégration dans le vrai parcours de scoring reste à faire par l’équipe Guardian. Le service n’implémente pas Twin/City Brain, token ou verdict déterministe.
- Les pénalités et seuils du panneau Reference rules sont une réimplémentation de la table du prompt, pas le scoring Guardian; confirmation inter-équipes encore nécessaire.
- Le modèle provient d’entraînement synthétique; un cas adaptatif progressif et corroboré peut lui échapper. Le PDF du rapport Guardian fourni était composé d’images et n’a pas pu être vérifié intégralement par extraction de texte.
- Le build signale un bundle JavaScript minifié supérieur à 500 kB (environ 554 kB), principalement dû au client MCP navigateur. La compilation réussit; découpage différé du bundle non entrepris.
- Aucun commit n’a été créé : `C:\Users\Dell\Documents\guardian` n’est pas un dépôt Git. Le dépôt Git du répertoire de travail parent est un autre projet Robot Framework déjà modifié; il n’a pas été utilisé pour committer l’application.
