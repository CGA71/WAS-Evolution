# Inventories

**EN** — One directory per environment. Everything that differs between environments lives here; everything product-specific lives in the collection's role defaults; everything that is configuration *intent* lives in `model/`.

**FR** — Un répertoire par environnement. Tout ce qui diffère entre environnements vit ici ; tout ce qui est spécifique au produit vit dans les `defaults/` des rôles ; tout ce qui est *intention* de configuration vit dans `model/`.

```
inventories/
  rit/      phase 1   traditional + IBM Java 8
  ra/       phase 2   liberty_more + Semeru 21     <- the pilot
  ru/       phase 1   traditional + IBM Java 8
  prd/      phase 1   traditional + IBM Java 8, deliberately on FP007
  k3s_sim/  CI        the same groups, over kubernetes.core.kubectl
```

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

Two held the same string, six were derivable, and all eight had to be edited to create an environment. Here it is two lines:

**FR** — L'inventaire source déclarait huit variables pour cela. Deux portaient la même chaîne, six étaient dérivables, et les huit devaient être éditées pour créer un environnement. Ici, deux lignes :

```yaml
# inventories/rit/group_vars/all/10_environment.yml
was_environment: RIT
was_channel: Extranet
```

The long name, the letter, the tier and the promotion rank come from `was_environment_catalog` in [`roles/model/vars/environments.yml`](../ansible_collections/wasevo/websphere/roles/model/vars/environments.yml). The `model` role refuses an unknown code and names the known ones.

Le nom long, la lettre, le palier et le rang de promotion viennent du catalogue. Le rôle `model` refuse un code inconnu et nomme ceux qu'il connaît.

### Adding an environment / Ajouter un environnement

1. Add an entry to `was_environment_catalog` — `long_name`, `letter`, `tier`, `rank`.
2. Copy an existing inventory directory and edit `10_environment.yml`, `40_runtime.yml` and `hosts.yml`.

Nothing else. / Rien d'autre.

> `confirmed: false` in the catalogue means the value was never verified against the naming standard. Only RIT was ever declared in the source inventory, where the letter was `I`. The `model` role warns while that flag is false.

## File layout / Découpage des fichiers

| File | Holds | Differs per environment? |
|---|---|---|
| `all/00_site.yml` | DNS domain, binaries share, WAS account, timezone | **No — byte-identical, enforced in CI** |
| `all/10_environment.yml` | `was_environment`, `was_channel` | Yes, and that is the point |
| `all/20_paths.yml` | Every filesystem path, derived from bases | No in practice, free to differ |
| `all/30_install.yml` | IBM artefacts: packages, repositories, versions | **Yes** — fixpack levels differ during a rollout |
| `all/40_runtime.yml` | `runtime.product`, `runtime.jdk`, WAS object names, ports | **Yes** — this is the trajectory switch |
| `dmgr.yml`, `nodeagents.yml` | Per-role profile and node naming | No |

### Why `00_site.yml` is duplicated

**EN** — Ansible cannot merge a shared `group_vars` across separate inventories without either a symlink, which does not survive a Windows checkout, or a second `-i` on every command, which everyone eventually forgets. A checked duplicate is the honest trade: the `site-vars-drift` CI job compares the SHA-256 of every copy and fails on the first difference. The drift is mechanically detected instead of discovered months later.

**FR** — Ansible ne sait pas fusionner un `group_vars` partagé entre inventaires distincts sans lien symbolique (qui ne survit pas à un checkout Windows) ni second `-i` sur chaque commande (que tout le monde finit par oublier). Le doublon contrôlé est le compromis honnête : le job CI `site-vars-drift` compare le SHA-256 de chaque copie et échoue à la première différence.

## Installation artefacts / Artefacts d'installation

**EN** — One dictionary instead of twenty flat `*_package_name` / `*_package_dir` / `verifVersion*` variables, for two reasons.

**First, a missing field becomes detectable.** The source inventory shipped `verifVersionSdk:` with no value, so it was `None`, and every `{{ verifVersionSdk }}` rendered the string `"None"`. With `shell:` and no validation, nothing ever reported it. The `model` role now asserts that every declared artefact carries a non-empty `verify_version`.

**Second, fixpack levels legitimately differ between environments.** RIT runs ahead, PRD runs behind. `prd/` really is on FP007 here while the others are on FP009 — that is the situation this structure exists to represent, rather than forcing a single global level.

**FR** — Un dictionnaire au lieu de vingt variables plates, pour deux raisons. **D'abord, un champ manquant devient détectable** : l'inventaire source livrait `verifVersionSdk:` sans valeur, donc `None`, et chaque référence rendait la chaîne `"None"` sans que rien ne le signale. **Ensuite, les niveaux de fixpack diffèrent légitimement** entre environnements : `prd/` est ici réellement en FP007 quand les autres sont en FP009.

The source inventory also defined some of these **twice with different values** — `sdk_fixpack_package_dir` pointed at two different fixpack directories, and `was_profiles_manager_cmd` was once hardcoded and once derived. Which one won depended on `group_vars` precedence. Single, derived definitions here.

## The trajectory switch / Le basculement de trajectoire

**EN** — Compare `rit/` and `ra/`. The entire difference in runtime is four values:

```yaml
runtime:
  product: liberty_more   # was: traditional
  jdk:
    version: 21           # was: 8
    vm: openj9            # was: j9
```

That switch routes the whole play to the Liberty back-end instead of the wsadmin one. The `model` role refuses the pair if it is unsupported — `traditional` cannot go past Java 8, and `liberty_ocp` refuses IBM Java 8 because its only image variant is the retired UBI Standard.

**FR** — Comparez `rit/` et `ra/` : toute la différence de runtime tient en quatre valeurs. Ce basculement route la totalité du play vers le back-end Liberty au lieu du back-end wsadmin, et le rôle `model` refuse le couple s'il n'est pas supporté.

## Production / Production

**EN** — `prd/` is `tier: prod` in the catalogue, and the `model` role refuses to run against it without `-e model_allow_production=true`. The AAP workflow carries an Approval Node for the same purpose at the other end. Reaching production should never be something that happens by typing the wrong inventory path. The CI pipeline asserts both halves: that `prd` is refused, and that it passes once acknowledged.

**FR** — `prd/` est `tier: prod` et le rôle `model` refuse de s'exécuter dessus sans `-e model_allow_production=true`. Le workflow AAP porte un Approval Node dans le même but à l'autre bout. Atteindre la production ne doit jamais être le résultat d'un mauvais chemin d'inventaire. La CI vérifie les deux moitiés : que `prd` est refusé, et qu'il passe une fois acquitté.

## Usage

```sh
# validate an environment without touching anything
ansible-playbook -i inventories/rit \
  ansible_collections/wasevo/websphere/playbooks/model_validate.yml

# check every declared forge dependency
ansible-playbook -i inventories/rit \
  ansible_collections/wasevo/websphere/playbooks/forge_preflight.yml

# control side only, when no target is reachable
ansible-playbook -i inventories/rit \
  ansible_collections/wasevo/websphere/playbooks/forge_preflight.yml \
  -e forge_preflight_control_only=true

# configure, dry run first - always
ansible-playbook -i inventories/rit \
  ansible_collections/wasevo/websphere/playbooks/traditional_config.yml --check --diff
```
