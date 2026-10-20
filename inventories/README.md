# Inventories

**EN** — **One** inventory, `was/`. The environment is an **input**, not a directory: it arrives as `was_environment`, answered in the AWX Survey at launch.

**FR** — **Un seul** inventaire, `was/`. L'environnement est une **entrée**, pas un répertoire : il arrive par `was_environment`, renseigné dans le formulaire AWX au lancement.

```
inventories/
  was/        every environment, parameterised
  k3s_sim/    the CI simulation, same groups, over kubernetes.core.kubectl
```

> An earlier shape in this repository had four near-identical directories — `rit/`, `ra/`, `ru/`, `prd/`. Four copies of the same site facts is four chances to drift, and it needed a CI job comparing checksums to catch it. That job is gone because the drift can no longer happen.
>
> Une forme antérieure avait quatre répertoires quasi identiques. Quatre copies des mêmes faits de site, c'est quatre occasions de divergence, et il fallait un job de CI comparant des empreintes pour l'attraper. Ce job a disparu parce que la divergence n'est plus possible.

## How the environment selects its hosts

**EN** — Every host belongs to **two** groups: one naming *where* it lives, one naming *what it does*. A play takes the intersection.

**FR** — Chaque hôte appartient à **deux** groupes : l'un nomme *où* il vit, l'autre *ce qu'il fait*. Un play prend l'intersection.

```yaml
hosts: "{{ was_environment | lower }}:&dmgr"
```

| `was_environment` | Resolves to / Résout vers |
|---|---|
| `RIT` | `rit:&dmgr` → `rit-dmgr-01` |
| `RA` | `ra:&dmgr` → `ra-dmgr-02` |
| `PRD` | `prd:&nodeagents` → `prd-was-01`, `prd-ihs-01` |

Supplied three ways, in increasing precedence:

| Source | Value |
|---|---|
| `group_vars/all/10_environment.yml` | `RIT` — the default, so a run with no input lands on the least dangerous environment |
| `-e was_environment=RA` | command line |
| **AWX Survey** | the answer to *Target environment* |

## The environment is one fact, not eight

**EN** — The source inventory declared eight variables for this:

```yaml
environnement_nom_long_majuscule: "RIT"      # same string...
environnement_nom_long_minuscule: "rit"
environnement_trigramme_majuscule: "RIT"     # ...as this one, both by hand
environnement_trigramme_minuscule: "rit"
environnement_lettre_majuscule: "I"
environnement_lettre_minuscule: "i"
canal: "Extranet"
canal_minuscule: "extranet"
```

Two held the same string, six were derivable, and all eight had to be edited to create an environment. The long name, letter, tier and promotion rank now come from `was_environment_catalog` in [`roles/model/vars/environments.yml`](../ansible_collections/wasevo/websphere/roles/model/vars/environments.yml). The `model` role refuses an unknown code and names the known ones.

**FR** — L'inventaire source déclarait huit variables pour cela. Deux portaient la même chaîne, six étaient dérivables, et les huit devaient être éditées pour créer un environnement. Le nom long, la lettre, le palier et le rang de promotion viennent désormais du catalogue.

> `confirmed: false` in the catalogue means the value was never verified against the naming standard. Only RIT was ever declared in the source inventory, where the letter was `I`. The `model` role warns while that flag is false.

### Adding an environment / Ajouter un environnement

1. Add an entry to `was_environment_catalog` — `long_name`, `letter`, `tier`, `rank`.
2. Add the hosts to `was/hosts.yml`, in the new environment group **and** in the role groups.
3. Add `was/group_vars/<name>.yml` with whatever differs — often just `was_base_port`.
4. Add the code to the Survey choices.

No new directory, no copied file. / Aucun répertoire, aucun fichier copié.

## File layout / Découpage des fichiers

| File | Holds |
|---|---|
| `group_vars/all/00_site.yml` | DNS domain, binaries share, WAS account, timezone. **One copy** |
| `group_vars/all/10_environment.yml` | The `was_environment` and `was_channel` inputs, and their defaults |
| `group_vars/all/20_paths.yml` | Every filesystem path, derived from bases |
| `group_vars/all/30_install.yml` | IBM artefacts baseline, plus the merge of per-environment overrides |
| `group_vars/all/40_runtime.yml` | `runtime` defaults, WAS object names, port arithmetic |
| `group_vars/all/50_connection.yml` | `ansible_host` built from the short name and the site domain |
| `group_vars/rit.yml` … `prd.yml` | Only what differs for that environment |
| `group_vars/dmgr.yml`, `nodeagents.yml` | Per-role profile and node naming, any environment |

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
  -e was_environment=RIT

# control side only, when no target is reachable
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/forge_preflight.yml \
  -e was_environment=RIT -e forge_preflight_control_only=true

# configure, dry run first - always
ansible-playbook -i inventories/was \
  ansible_collections/wasevo/websphere/playbooks/traditional_config.yml \
  -e was_environment=RIT --check --diff
```

In AWX none of these flags are typed: the Survey asks for the environment, the channel and the production acknowledgement, and the Job Template offers check mode as a launch prompt.

Dans AWX aucun de ces drapeaux n'est saisi : le formulaire demande l'environnement, le canal et l'acquittement production, et le Job Template propose le mode simulation au lancement.
