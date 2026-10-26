# Inventories

**EN** — **One** inventory, `was/`. The environment is an **input**, not a directory: it arrives as `was_environment`, answered in the AWX Survey at launch.

**FR** — **Un seul** inventaire, `was/`. L'environnement est une **entrée**, pas un répertoire : il arrive par `was_environment`, renseigné dans le formulaire AWX au lancement.

```
inventories/
  was/        every environment, parameterised
  k3s_sim/    the CI simulation, same groups, over kubernetes.core.kubectl
```

> An earlier shape in this repository had four near-identical directories, one per environment. Four copies of the same site facts is four chances to drift, and it needed a CI job comparing checksums to catch it. That job is gone because the drift can no longer happen.
>
> Une forme antérieure avait quatre répertoires quasi identiques, un par environnement. Quatre copies des mêmes faits de site, c'est quatre occasions de divergence, et il fallait un job de CI comparant des empreintes pour l'attraper. Ce job a disparu parce que la divergence n'est plus possible.

## How the environment selects its hosts

**EN** — Every host belongs to **two** groups: one naming *where* it lives, one naming *what it does*. A play takes the intersection.

**FR** — Chaque hôte appartient à **deux** groupes : l'un nomme *où* il vit, l'autre *ce qu'il fait*. Un play prend l'intersection.

```yaml
hosts: "{{ was_environment | lower }}:&dmgr"
```

| `was_environment` | Resolves to / Résout vers |
|---|---|
| `ENVCODE` | `envcode:&dmgr` -> the dmgr machine of that group |
| `ENVCODE` | `envcode:&nodeagents` -> its node agent machines |

The group name is the answer in lowercase. There is **no list of environment codes anywhere in the collection** - create the group, and the code works. The `model` role refuses an answer with no matching group and names the groups it found.

Le nom du groupe est la réponse en minuscules. Il n'existe **aucune liste de codes d'environnement dans la collection** : on crée le groupe, et le code fonctionne. Le rôle `model` refuse une réponse sans groupe correspondant et nomme les groupes trouvés.

Supplied two ways, in increasing precedence / Fourni de deux façons, par précédence croissante :

| Source | Value |
|---|---|
| `-e was_environment=<code>` | command line |
| **AWX Survey** | the answer to *target environment* |

There is deliberately **no default**. A default would mean that a run with no answer silently rebuilds one particular environment.

Il n'y a volontairement **aucun défaut**. Un défaut signifierait qu'un run sans réponse reconstruit silencieusement un environnement donné.

## Machine names come from the inventory

**EN** - `hosts.yml` is the only place a machine is named, and the collection composes nothing from the name: it reads what the file says. An earlier version carried a former client's naming standard (`ln` + environment letter + role + index), which read like a rule the code could rely on.

**FR** - `hosts.yml` est le seul endroit où une machine est nommée, et la collection ne compose rien à partir du nom : elle lit ce que le fichier déclare. Une version antérieure portait la nomenclature d'un ancien client, qui se lisait comme une règle dont le code pouvait dépendre.

## The environment is one fact, not eight

**EN** - The source inventory declared eight variables for this:

```yaml
environnement_nom_long_majuscule: "<ENV>"      # same string...
environnement_nom_long_minuscule: "<env>"
environnement_trigramme_majuscule: "<ENV>"     # ...as this one, both by hand
environnement_trigramme_minuscule: "<env>"
environnement_lettre_majuscule: "<E>"
environnement_lettre_minuscule: "<e>"
canal: "Extranet"
canal_minuscule: "extranet"
```

Two held the same string, six were derivable, and all eight had to be edited to create an environment. Now **one** value arrives from the survey and both cases are derived from it in [`roles/model/vars/environments.yml`](../ansible_collections/wasevo/websphere/roles/model/vars/environments.yml) - upper for object names, lower for paths, groups and DNS. The letter defaults to the first letter of the code; the tier is its own input, because an open environment value means no code can know which codes a site calls production.

**FR** - L'inventaire source déclarait huit variables pour cela. Deux portaient la même chaîne, six étaient dérivables, et les huit devaient être éditées pour créer un environnement. Désormais **une** valeur arrive du formulaire et les deux casses en sont dérivées : majuscule pour les noms d'objets, minuscule pour les chemins, les groupes et le DNS. La lettre vaut par défaut la première du code ; le palier est une entrée à part, puisqu'une valeur ouverte interdit au code de savoir quels codes un site appelle production.

## Object names are composed once

**EN** - The cell, the deployment manager profile and node, the node agent node, the cluster, its JVM members and the shared class cache are all composed in [`roles/model/vars/naming.yml`](../ansible_collections/wasevo/websphere/roles/model/vars/naming.yml), from the environment and the channel. They used to be written out in three inventories, with the cluster name hardcoded in two of them. Declare a name in an inventory to override the pattern - the role never overwrites a name that already exists.

**FR** - La cellule, le profil et le nœud du gestionnaire de déploiement, le nœud de l'agent, le cluster, ses JVM et le cache de classes partagées sont composés en un seul endroit, à partir de l'environnement et du canal. Ils étaient auparavant réécrits dans trois inventaires, avec le nom de cluster en dur dans deux d'entre eux. Déclarer un nom dans un inventaire surcharge le motif : le rôle n'écrase jamais un nom existant.

### Adding an environment / Ajouter un environnement

1. Add the hosts to `was/hosts.yml`, in a new environment group named with the code in lowercase **and** in the role groups.
2. Add `was/group_vars/<code>.yml` with whatever differs — often just `was_base_port`, plus `was_environment_tier: prod` where it applies. See [`was/group_vars/README.md`](was/group_vars/README.md).
3. Add the code to the Survey choices.

No code change. / Aucune modification de code.

No new directory, no copied file. / Aucun répertoire, aucun fichier copié.

## What to fill in, in order / Ce qu'il faut remplir, dans l'ordre

**EN** — Building a WAS environment means filling these, in this order. Only
the first four carry placeholders that are certainly wrong for your site.

| # | File | What to put there | Today |
|---|---|---|---|
| 1 | `was/hosts.yml` | the environment group name, the machine names, and which role group each machine is in | **placeholders**: `envcode`, `dmgr-01`, `app-01`, `web-01` |
| 2 | `was/group_vars/all/00_site.yml` | DNS domain, the share holding the IBM installers, timezone, the service account and group | **placeholders**: `example.internal`, `//fileserver/ISO` |
| 3 | `was/group_vars/all/10_environment.yml` | the site's channel, which becomes part of the cell and cluster names | `Extranet` — change it if the site says otherwise |
| 4 | `was/group_vars/<environment>.yml` | one file per environment group, **only what differs from `all/`**: port base, `was_environment_tier`, optional long name and letter | **to create** — none exist; template above |
| 5 | `was/group_vars/all/20_paths.yml` | two roots only — `was_app_base_dir` and `was_install_binaries_base_dir`. Everything else is derived from them | `/app` and `/mnt/binaries` |
| 6 | `was/group_vars/all/25_install_dirs.yml` | nothing, unless a path has to leave the two roots above | all derived |
| 7 | `was/group_vars/all/40_runtime.yml` | the product × JDK couple and the port base | `traditional` + Java 8, base 30000 |
| 8 | `was/group_vars/all/50_connection.yml` | nothing, unless the SSH user differs from the service account | derived from `00_site.yml` |
| 9 | `was/group_vars/dmgr.yml`, `nodeagents.yml` | what the machine does, never where it lives | service names |
| 10 | `was/group_vars/all/30_install.yml` | the IBM artefact dictionary. See the caveat below | still carries the source estate's package stamps |

Three things that are deliberately **not** in the inventory: credentials, which
come from an AWX Credential; the environment code, which is a survey answer;
and the WAS object names, which are composed unless a survey answer or a
`group_vars` entry overrides them.

Two caveats worth knowing before spending time on them.

`30_install.yml` is read by one place only — the `model` role, which asserts
every declared artefact carries a non-empty `verify_version`. It is validated,
not consumed: `was_install` and `was_fixpack` **discover** the offering from the
repository instead, because the editions differ only by an offering id and a
wrong guess produces an `imcl` error that reads like a licence problem. So the
package stamps in it are shape, not instruction.

`was_dmgr_host` in `nodeagents.yml` is read by nothing. `profile_nodeagent`
resolves the deployment manager from `groups['dmgr']` and reads its real SOAP
port from the created profile, which is the thing that cannot disagree with
reality.

**FR** — Construire un environnement WAS, c'est remplir ces fichiers, dans cet
ordre. Seuls les quatre premiers portent des valeurs de remplacement
certainement fausses pour votre site : le groupe d'environnement et les noms de
machines dans `hosts.yml`, le domaine DNS et le partage des médias dans
`00_site.yml`, le canal dans `10_environment.yml`, et un fichier par
environnement dans `group_vars/` — il n'en existe aucun aujourd'hui.

Les chemins (5 et 6) ne demandent que deux racines, `was_app_base_dir` et
`was_install_binaries_base_dir` ; tout le reste en dérive. Les identifiants ne
sont pas dans l'inventaire : ils viennent d'une Credential AWX. Le code
d'environnement non plus : c'est une réponse du survey. Les noms d'objets WAS
non plus : ils sont composés, sauf surcharge.

## File layout / Découpage des fichiers

| File | Holds |
|---|---|
| `group_vars/all/00_site.yml` | DNS domain, binaries share, WAS account, timezone. **One copy** |
| `group_vars/all/10_environment.yml` | The `was_environment` and `was_channel` inputs, and their defaults |
| `group_vars/all/20_paths.yml` | Every filesystem path, derived from bases |
| `group_vars/all/30_install.yml` | IBM artefacts baseline, plus the merge of per-environment overrides |
| `group_vars/all/40_runtime.yml` | `runtime` defaults and port arithmetic. No object names: those are composed in the `model` role |
| `group_vars/all/50_connection.yml` | `ansible_host` built from the short name and the site domain |
| `group_vars/<code>.yml` | Only what differs for that environment, including `was_environment_tier` |
| `group_vars/dmgr.yml`, `nodeagents.yml` | What the role needs on any machine playing it - paths and service names, not object names |

## Installation artefacts / Artefacts d'installation

**EN** — One dictionary instead of twenty flat `*_package_name` / `*_package_dir` / `verifVersion*` variables, for two reasons.

**A missing field becomes detectable.** The source inventory shipped `verifVersionSdk:` with no value, so it was `None`, and every `{{ verifVersionSdk }}` rendered the string `"None"`. With `shell:` and no validation, nothing ever reported it. The `model` role now asserts a non-empty `verify_version` per artefact.

**Fixpack levels legitimately differ between environments.** An environment that is mid-rollout overrides the one entry that differs, recursively merged over the baseline — see `prd.yml`, which really is on FP007 while the others are on FP009. With twenty flat variables that override would have meant carrying a whole copy of the list.

The source inventory also defined some of these **twice with different values** — `sdk_fixpack_package_dir` pointed at two different fixpack directories, and `was_profiles_manager_cmd` was once hardcoded and once derived. Which one won depended on `group_vars` precedence.

**FR** — Un dictionnaire au lieu de vingt variables plates. **Un champ manquant devient détectable** : l'inventaire source livrait `verifVersionSdk:` sans valeur, donc `None`, et chaque référence rendait la chaîne `"None"` sans que rien ne le signale. **Et les niveaux de fixpack diffèrent légitimement** : un environnement en cours de déploiement surcharge la seule entrée qui change, fusionnée récursivement sur la base — voir `prd.yml`, réellement en FP007.

## The trajectory switch / Le basculement de trajectoire

**EN** — `ra.yml` is the phase 2 pilot, and it is the whole cost of a trajectory change:

```yaml
runtime:
  product: liberty_more   # was: traditional
  jdk:
    version: 21           # was: 8
    vm: openj9            # was: j9
```

That routes the whole play to the Liberty back-end instead of the wsadmin one. The `model` role refuses the pair if it is unsupported — `traditional` cannot go past Java 8, and `liberty_ocp` refuses IBM Java 8 because its only image variant is the retired UBI Standard.

**FR** — `ra.yml` est le pilote de la phase 2, et c'est tout le coût d'un changement de trajectoire. Cela route la totalité du play vers le back-end Liberty, et le rôle `model` refuse le couple s'il n'est pas supporté.

## Production / Production

**EN** — `PRD` is `tier: prod` in the catalogue, and the `model` role refuses to run against it unless `model_allow_production` is true. In AWX that is a Survey question, deliberately defaulted to `false`, plus an Approval Node on the workflow. Reaching production should never be the result of picking the wrong answer. The CI pipeline asserts both halves: that `PRD` is refused, and that it passes once acknowledged.

**FR** — `PRD` est `tier: prod`, et le rôle `model` refuse de s'exécuter dessus sans `model_allow_production`. Dans AWX c'est une question du formulaire, volontairement par défaut à `false`, plus un Approval Node sur le workflow. Atteindre la production ne doit jamais résulter d'une mauvaise réponse. La CI vérifie les deux moitiés.

## Usage

```sh
# validate one environment without touching anything
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/model_validate.yml \
  -e was_environment=RA

# check every declared forge dependency
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/forge_preflight.yml \
  -e was_environment=<code>

# control side only, when no target is reachable
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/forge_preflight.yml \
  -e was_environment=<code> -e forge_preflight_control_only=true

# configure, dry run first - always
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/traditional_config.yml \
  -e was_environment=<code> --check --diff
```

In AWX none of these flags are typed: the Survey asks for the environment, the channel and the production acknowledgement, and the Job Template offers check mode as a launch prompt.

Dans AWX aucun de ces drapeaux n'est saisi : le formulaire demande l'environnement, le canal et l'acquittement production, et le Job Template propose le mode simulation au lancement.
