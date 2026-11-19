# Un second projet AWX sur `main` — solution mise de côté

**Statut : non réalisé, volontairement.** À reprendre quand AWX servira à plus
d'un environnement ou à plus d'une personne à la fois. Décision du 19 novembre
2026.

## Le principe

AWX exécute un **tag** (`v0.2.0`), posé par `ci/release.sh` et réglé par
`ci/awx/promote.sh` (README section 20). Le code validé et figé est donc ce qui
tourne — mais tester un changement poussé sur `main` oblige à basculer tout AWX
dessus.

La solution : **deux projets AWX sur le même dépôt Git**, à deux versions
différentes du code.

| Projet AWX | Code exécuté | Usage |
|---|---|---|
| `WAS Evolution` | un tag (`v0.2.0`), réglé par `promote.sh` | les vrais environnements (DEV01, VAL02…) |
| `WAS Evolution (dev)` | la branche `main`, `update_on_launch` | les essais sur le serveur de labo, juste après un push |

On teste le code en cours sans toucher à ce que les autres environnements
exécutent.

## Pourquoi ce n'est pas fait aujourd'hui

Dans AWX, un projet seul ne sert à rien : on lance des **job templates** et des
**workflows**, et chacun est rattaché à **un** projet. Un projet « dev » demande
donc un double de chaque template et de chaque workflow — la cellule, les
templates 9 à 24, les certificats, les applications.

Or les scripts `ci/awx/apply-*.sh` retrouvent les objets **par leur nom**, et
les noms des job templates sont écrits en dur. Relancés avec
`AWX_PROJECT="WAS Evolution (dev)"`, ils **réécriraient** les templates
existants pour les rattacher au projet dev, au lieu d'en créer de nouveaux.

Tant qu'AWX ne sert qu'au serveur de labo, la bascule
`promote.sh main --branch` / `promote.sh vX.Y.Z` suffit.

## Quand la reprendre

- un deuxième environnement est piloté par AWX (DEV01, VAL…) pendant qu'on
  continue d'essayer du code sur le labo ;
- ou plusieurs personnes lancent des jobs AWX, et une bascule de tout AWX sur
  `main` en surprendrait une.

## Ce qu'il faut faire

1. **Un suffixe de nom dans tous les scripts `apply-*`.** Une variable
   `AWX_NAME_SUFFIX` (vide par défaut, `" (dev)"` pour le projet dev), ajoutée au
   nom de **chaque** objet créé : job templates, workflows, nœuds, survey,
   planifications. Les workflows ont déjà leur variable
   (`AWX_CELL_WORKFLOW`, `AWX_APP_DEPLOY_WORKFLOW`…) ; les job templates
   (« 0. Binaries mount point », etc.) n'en ont pas — c'est l'essentiel du
   travail. Vide, le suffixe ne change rien à l'existant.

2. **Le projet dev, déclaré par script.** Dans `promote.sh` ou un
   `apply-dev-project.sh` : copier du projet `WAS Evolution` son `scm_url`, sa
   credential SCM, son organisation et son environnement d'exécution, avec
   `scm_branch: main` et `scm_update_on_launch: true`. Rejouable, retrouvé par
   son nom, comme le reste.

3. **Les objets dev :**
   ```sh
   export AWX_PROJECT="WAS Evolution (dev)" AWX_NAME_SUFFIX=" (dev)"
   bash ci/awx/apply-cell-workflow.sh
   bash ci/awx/apply-templates.sh
   bash ci/awx/apply-application-workflows.sh
   ```

4. **Les garde-fous du dev :**
   - les templates dev n'utilisent **que l'inventaire du labo** ; jamais un
     inventaire DEV, VAL ou production ;
   - le palier production reste refusé par le modèle sans
     `model_allow_production` — ne **jamais** le fournir dans un template dev ;
   - `promote.sh` refuse de régler le projet dev sur un tag, et le projet
     principal sur une branche sans `--branch` (déjà le cas pour ce dernier).

5. **Les droits AWX.** Le projet principal et ses templates : lancés par les
   exploitants. Le projet dev : réservé à ceux qui développent les playbooks.

6. **Documenter** dans la section 20 du README (anglais et français) et dans
   `ci/awx/README.md`.

## Ce que ça coûte

- deux fois plus d'objets dans AWX, à garder alignés (les scripts le font si
  on les relance pour les deux) ;
- les credentials faites à la main (« ServeurAIX (ansible) », « WAS
  administrative user ») sont partagées, pas dupliquées ;
- la CI ne change pas : elle valide `main` et les tags, sans savoir quel projet
  AWX les exécute.
