# Suivi du travail — état au 17 novembre 2026

Note de reprise **publique** : elle est publiée sur GitHub pour pouvoir reprendre
depuis un autre poste. Elle ne contient aucune adresse, aucun nom de machine et
aucun identifiant ; ceux-là restent dans les notes privées du dépôt GitLab.

---

## 1. Où on en est

**Dernière transformation : plus de Kubernetes, un serveur AIX physique.**
k3s, KubeVirt, l'installation d'AWX sur k3s et la simulation CI sur k3s sont
retirés. La cellule ND entière tourne sur **un serveur AIX physique** (`inventories/aix`) ;
AWX est hébergé ailleurs et piloté par les scripts `ci/awx` (jeton ou mot de
passe, `curl -sS -k --noproxy '*'`). La CI est en trois étapes :
**validation** (statique + point de montage des binaires + preflight AIX),
**build** (IM, WAS, fix packs, rejoués à `changed=0`), **deploy** (manuel :
profils, cluster, membres, démarrage, rejoués). README sections 15, 16, 20.

Livrés avec : le **déploiement et le décommissionnement d'application**
(rôle `traditional/application`, workflow AWX avec approbation, README section
24) et les **familles d'environnements** de la DSI — une famille, seule ou
avec une instance sur deux chiffres, qui décide du palier (README section 16).

À vérifier sur le vrai serveur : les filesets AIX attendus, la présence de
`unzip`/`zipinfo` dans le `PATH` par défaut, la sortie de `lslpp -Lc` et de
`mount` sur ce niveau d'AIX, et les variables CI/CD (section 15).

Précédemment : **Dernière fonctionnalité livrée : la gestion des certificats** — README
section 23 (anglais et français). Commits *Certificates: inventory, renewal by
issuer and a portal on AWX's host* puis *Lint stage green again*.

| Pièce | Où |
|---|---|
| Handler Jython (inventory, renew, request, receive, refresh_signer) | `plugins/jython/handlers/certificates.py` |
| Modules | `plugins/modules/was_certificate_info.py`, `was_certificate.py` |
| Inventaire des certificats (lecture seule, artefacts AWX) | rôle `traditional/certificates`, playbook `traditional_certificates.yml` |
| Renouvellement d'un certificat (selon l'émetteur) | rôle `traditional/certificate_renewal`, playbook `traditional_certificate_renewal.yml` |
| Portail statique servi sur l'hôte d'AWX | rôle `platform/certificate_portal`, playbook `platform_certificate_portal.yml` |
| Templates AWX par organisation + planification quotidienne | `ci/awx/apply-certificates.sh` |
| Tests | `ci/run-stub-tests.sh` (section certificats), `ci/portal-tests.js` |

Choix validés pour les certificats :

- renouvellement **selon l'émetteur** : signé par la cellule → `renewCertificate` ;
  signé par une CA → CSR puis réception de la réponse ; signataire → récupéré à
  nouveau sur le port du pair ; racine → affichée, jamais automatisée ;
- **un seul** job template de renouvellement, lancé avec des extra vars ;
- multi-client = **organisations AWX** ; la page utilise la session AWX de
  l'utilisateur (même origine, cookie CSRF), donc aucun jeton et les droits AWX
  font l'isolation ;
- échéance affichée : **3 mois** (90 jours), critique sous 30 jours.

**CI** : la simulation k3s est remplacée par validation / build / deploy sur le
serveur AIX. yamllint, les 41 syntax-checks et les tests stub passent en local ; **le premier
pipeline sur le vrai serveur reste à lire en premier**.

---

## 2. Ce qui reste à faire

1. **Relire le résultat complet du pipeline** du dernier commit, et lire le log
   brut de tout job en échec (pas seulement son statut).
2. **Certificats sur une vraie cellule** : lancer `apply-certificates.sh` pour
   une organisation, lancer « Certificates - portal » une fois, puis un
   inventaire, et ouvrir `https://<hôte AWX>/wasevo/certificates/`. À vérifier
   sur une vraie cellule : le texte de validité qu'imprime AdminTask dépend de
   la locale de la JVM. Le handler lit les trois formes connues (noms de mois,
   numérique US, ISO) ; une date illisible ressort en statut `unknown` — si le
   portail en montre, il faut ajouter la forme rencontrée.
3. **Applications sur une vraie cellule** (README section 24) : déployer une
   petite application déclarée dans `was_applications`, la rejouer
   (`changed=0`), puis la décommissionner par le workflow AWX. À vérifier sur
   WAS réel : les libellés de `AdminApp.view` (cibles, bibliothèques, JNDI),
   l'emplacement de l'archive d'un WAR dans `applications/<nom>.ear/`, et
   `removeNode.sh` avec les identifiants posés le temps de la commande dans
   `soap.client.props`. Reste à faire ensuite : les attachements de policy sets
   au déploiement. MicroProfile vient en phase 2 (Liberty).
4. `WAS-Evolution.code-workspace` a un reformatage local non commité, sans
   rapport avec le reste — à jeter ou à commiter à part.
5. **Versions** : AWX exécute un tag (`ci/release.sh`, `ci/awx/promote.sh`,
   README section 20). Protéger les tags `v*` dans GitLab, puis faire la
   première release `v0.1.0`. Le second projet AWX sur `main` est mis de côté
   tant qu'AWX ne sert qu'au labo : la solution est dans
   [`docs/AWX-PROJET-DEV.md`](docs/AWX-PROJET-DEV.md).

---

## 3. Règles du projet (à respecter en reprenant)

- **Aucun code d'environnement** dans le code, un défaut, un exemple ou un
  test : l'environnement vient de la réponse au survey AWX. En test, utiliser
  `ENVCODE` ; pour une cellule d'exemple, `MyCell` / `TestCell`.
- **Aucun nom de machine** dans la collection : ils vivent dans l'inventaire.
- Les noms d'objets WAS (cellule, cluster, serveurs, node agents) sont des
  **entrées** (inventaire ou survey `survey_*`), jamais une convention codée.
- **Un rôle = un playbook = un job template AWX**, rejouable seul (une session
  wsadmin, pas toute la chaîne). Les **8 familles d'API** cataloguent les rôles
  (README section 19) : on regroupe par playbook, on ne fusionne jamais.
- **La CI valide, construit, puis déploie sur le serveur AIX** — le deploy est
  manuel, sur la branche par défaut seulement.
- **Chaque fonctionnalité** : README dans les **deux langues**, puis commit et
  push avec un message qui la nomme.

---

## 4. Travailler depuis un autre poste

Le dépôt de travail est **GitLab** (historique réel). GitHub reçoit seulement
une **copie réécrite** (git-filter-repo : chemins privés retirés, adresses du
lab et identités remplacées), produite par un script **hors du dépôt**, sur le
poste principal (`D:\WAS-Evolution-publish\publish.sh`).

Conséquences :

- les hashes de GitHub **ne sont pas** ceux de GitLab : ne jamais pousser une
  branche GitHub vers GitLab, ni l'inverse ;
- depuis un clone GitHub, travailler normalement puis **rapporter les commits
  sous forme de patchs** :

  ```sh
  # sur le portable, dans le clone GitHub
  git format-patch origin/main --output-directory ../patchs

  # sur le poste principal, dans le dépôt GitLab
  git am ../patchs/*.patch
  git push origin master
  ```

- puis republier GitHub depuis le poste principal :
  `bash D:/WAS-Evolution-publish/publish.sh --push` — une avance rapide
  normale (le dernier push forcé, pour le changement d'adresse d'auteur, est
  fait).

Tests sans serveur, sur n'importe quel poste avec Python 3 et Node :

```sh
PYTHON=python bash ci/run-stub-tests.sh     # ALL CHECKS PASSED attendu
node ci/portal-tests.js                     # ALL CHECKS PASSED attendu
```
