# AWX — ordre d'installation des objets

Ce document donne l'ordre dans lequel lancer les scripts de `ci/awx/` pour créer,
dans un AWX vide, tous les objets du projet WAS Evolution. Ordre validé le
2026-11-23 sur un AWX 24.6.1 vierge, avec le projet sur la branche `features` :
tous les scripts sont passés sans erreur.

Les scripts tournent depuis n'importe quel hôte qui joint AWX. Ils demandent
`bash`, `curl` et `python3`. Ils sont rejouables : chaque objet est retrouvé par
son nom et mis à jour.

## 1. À créer à la main dans AWX, une seule fois

Aucun script ne crée ces objets : ils portent un secret ou un choix de site.

| Objet | Nom attendu | Remarque |
|---|---|---|
| Projet | `WAS Evolution` | Git, `https://github.com/CGA71/WAS-Evolution.git`, **branche `features`**, environnement d'exécution par défaut renseigné |
| Credential machine | `ServeurAIX (ansible)` | clé SSH du compte WAS sur ServeurAIX |
| Environnement d'exécution | — | au moins un job template doit en porter un : `apply-cell-workflow.sh` le reprend (sinon `could not work out which Execution Environment to use`) |
| Credential vault | `WAS AIX vault` | optionnelle, voir `docs/vault.md` ; utile seulement si `sudo su -` demande un mot de passe |
| Credential WAS | type `WAS administrative user` | optionnelle, à créer **après** l'étape 2 qui crée le type ; sans elle les templates la demandent au lancement |

**Branche du projet.** Les playbooks de fix pack (`traditional_jvm_stop.yml`,
`traditional_jvm_start.yml`, `traditional_fixpack_dmgr.yml`,
`traditional_fixpack_ihs.yml`) n'existent que sur `features`. Un projet sur une
autre branche fait échouer l'étape 4 avec
`{"playbook": ["Playbook not found for project."]}`.

## 2. Connexion à AWX

```sh
export AWX_API=https://<awx>/api/v2
export AWX_TOKEN_FILE=~/.awx-token     # optionnel : jeton AWX, sinon mot de passe d'admin demandé à chaque script
# export AWX_CA_FILE=/chemin/ca.pem    # optionnel : vérifie le certificat d'AWX, sinon curl -k
```

## 3. Ordre des scripts

```sh
bash ci/awx/apply-cell-workflow.sh            # 1
bash ci/awx/apply-templates.sh                # 2
bash ci/awx/apply-survey.sh                   # 3
bash ci/awx/apply-fixpack.sh                  # 4
bash ci/awx/apply-application-workflows.sh    # 5
AWX_INVENTORY="WAS AIX" \
  bash ci/awx/apply-certificates.sh           # 6
```

| # | Script | Crée | A besoin de |
|---|---|---|---|
| 1 | `apply-cell-workflow.sh` | inventaire `WAS AIX` et sa source, templates 0 à 8, workflow `WAS AIX - cell on ServeurAIX` ; lance aussi `apply-survey.sh` | projet, credential machine, un environnement d'exécution |
| 2 | `apply-templates.sh` | templates de configuration 9 à 23, ajoutés au workflow ; type de credential `WAS administrative user` | étape 1 |
| 3 | `apply-survey.sh` | formulaire du workflow et des templates, invite *Job type* (Check) | étapes 1 et 2 — à relancer après 2 pour couvrir les nouveaux templates |
| 4 | `apply-fixpack.sh` | templates fix pack deployment manager et IHS/plugin, arrêt/démarrage des JVM par lot, workflow `WAS AIX - Fix pack WAS by JVM batch` | étape 1 (inventaire, template `WAS AIX - 2. Fix packs: Installation Manager`), projet sur `features` |
| 5 | `apply-application-workflows.sh` | workflows `WAS AIX - Application: deploy` et `decommission`, template `Applications - portal` | étape 1 |
| 6 | `apply-certificates.sh` | templates de certificats et leur planification, par organisation | `AWX_INVENTORY` et/ou `AWX_PORTAL_INVENTORY` **obligatoires** |

Les étapes 4 et 5 s'arrêtent avec `run apply-cell-workflow.sh first` si
l'étape 1 n'a pas été faite.

## 4. Variables utiles

| Variable | Défaut | Script |
|---|---|---|
| `AWX_PROJECT` | `WAS Evolution` | tous |
| `AWX_MACHINE_CRED` | `ServeurAIX (ansible)` | tous |
| `AWX_CELL_INVENTORY` / `AWX_INVENTORY` | `WAS AIX` | 1, 2, 4, 5 |
| `AWX_VAULT_CRED` | `WAS AIX vault` | 4 |
| `AWX_APP_INVENTORY_ENVIRONMENTS` | vide | 5 — vide : pas de lecture quotidienne planifiée |
| `AWX_WEB_MACHINE_CRED` | `AWX web front (ansible)` | 5 — absente : à rattacher à la main au template du portail |
| `AWX_ORGANIZATION` | `Default` | 6 |
| `AWX_INVENTORY`, `AWX_PORTAL_INVENTORY` | vides | 6 — au moins un des deux |

## 5. Vérifier

```sh
bash ci/awx/apply-cell-workflow.sh --show     # graphe du workflow de la cellule
bash ci/awx/apply-fixpack.sh --show           # nœuds du workflow fix pack
bash ci/awx/apply-survey.sh --show            # formulaires attachés
```

Attendu après les six étapes : le projet, l'inventaire `WAS AIX`, quatre
workflows (cellule, fix pack WAS par lot de JVM, déploiement et
décommissionnement d'application) et leurs templates.
