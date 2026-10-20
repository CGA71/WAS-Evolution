# Architecture — notes de référence / reference notes

> **FR** — Le document d'architecture complet, destiné à circuler pour validation, est publié ici :
> <https://claude.ai/artifact/XEUWFCxUbHy8K3F8RXebtk>
>
> **EN** — The full architecture document, written to circulate for sign-off, is published here:
> <https://claude.ai/artifact/XEUWFCxUbHy8K3F8RXebtk>

Le `README.md` à la racine en est la version versionnée, bilingue, et c'est elle qui fait référence pour le code. Ce fichier ne garde que ce qui n'a pas sa place dans un README : les points de conception qu'il faut pouvoir retrouver quand on se demande *pourquoi* le code est comme ça.

The root `README.md` is the versioned, bilingual form, and it is authoritative for the code. This file keeps only what does not belong in a README: the design points someone will need when they wonder *why* the code looks the way it does.

---

## Pourquoi le driver Jython existe / Why the Jython driver exists

**FR** — Un module Ansible s'exécute sous le Python 3 de la cible. wsadmin exige Jython dans la JVM de WAS. Les deux ne peuvent pas partager un processus. Le module écrit donc un payload, lance wsadmin **une fois**, et relit un JSON.

C'est ce qui donne le gain de temps : le legacy démarrait deux JVM par objet (`*Exist.py` puis `*Add.py`), à 30-60 s chacune. Ici le `read`, la comparaison et le `write` tiennent dans une seule session.

**EN** — An Ansible module runs under the target's Python 3. wsadmin requires Jython inside WAS's JVM. The two cannot share a process, so the module writes a payload, launches wsadmin **once**, and reads a JSON answer back.

That is where the time saving comes from: the legacy code started two JVMs per object (`*Exist.py` then `*Add.py`) at 30-60 s each. Here read, compare and write all happen in one session.

### Contrat des handlers / Handler contract

Chaque handler expose les mêmes callables, ce qui permet à `driver.py` de rester générique :

Every handler exposes the same callables, which is what lets `driver.py` stay generic:

```python
read(admin, params)                 # -> dict de l'état réel, {} si absent
plan_present(admin, params, before) # -> (changed, after)   SANS rien modifier
plan_absent(admin, params, before)  # -> (changed, after)
write_present(admin, params, before)
write_absent(admin, params, before)
sync(admin, params)                 # optionnel
```

La séparation `plan_*` / `write_*` **est** le `--check`. Le `plan` tourne toujours, y compris en mode simulation, donc l'écart est calculé et montrable avant toute écriture.

The `plan_*` / `write_*` split **is** `--check`. The plan half always runs, including in check mode, so the gap is computed and displayable before anything is written.

### Pièges Jython / Jython traps

| | |
|---|---|
| `json` | Absent en Jython 2.1 (anciens fixpacks), présent en 2.7. `driver.py` tente l'import et embarque un encodeur minimal sinon. / Absent on Jython 2.1, present on 2.7. `driver.py` tries the import and bundles a minimal encoder otherwise. |
| `AdminConfig` et cie | Injectés dans les globals du script **principal**. Un module importé ne les voit pas : ils sont passés explicitement dans le dict `admin`. / Injected into the **main** script's globals. An imported module does not see them, so they are passed explicitly in the `admin` dict. |
| `sys.argv[0]` | C'est le premier argument du script, pas son nom. / It is the first script argument, not the script name. |
| Sentinelles | wsadmin imprime ses bannières (`WASX7209I`…) autour de notre sortie. Le driver encadre sa réponse plutôt que d'espérer un stdout propre. / wsadmin prints banners around our output. The driver fences its answer rather than hoping stdout is clean. |

---

## Pourquoi aucun module côté Liberty / Why no modules on the Liberty plane

**FR** — Les modules `was_*` existent parce que wsadmin est impératif et qu'il faut y *fabriquer* l'idempotence. `kubernetes.core.k8s` fait déjà le lire-puis-écrire, avec un `changed` réel et un `--diff` réel via server-side apply. Écrire des modules Liberty serait réécrire `kubernetes.core` en moins bien.

Corollaire inattendu : le plan OpenShift devient le **mieux instrumenté des deux**, gratuitement. Le `shell: kubectl apply` du dépôt source remonte toujours `changed` et ne produit aucun diff.

**EN** — `was_*` modules exist because wsadmin is imperative and idempotency has to be *manufactured*. `kubernetes.core.k8s` already does check-then-change with a truthful `changed` and a real `--diff` through server-side apply. Writing Liberty modules would re-implement `kubernetes.core`, worse.

An unexpected corollary: the OpenShift plane ends up the **better instrumented of the two**, for free. The source repository's `shell: kubectl apply` always reports `changed` and produces no diff.

---

## La frontière GitOps / The GitOps boundary

**FR** — `config_render` ne touche pas le cluster. Il s'exécute hors ligne, il est validable en CI, et il produit des fichiers. `deploy` est la seule chose qui parle à l'API.

Si Argo CD est adopté : `config_render` produit et commite, `deploy` est débranché, **rien d'autre ne bouge**. C'est pour ça que ces deux rôles ne doivent jamais fusionner, même quand ce serait plus court.

**EN** — `config_render` does not touch the cluster. It runs offline, it is gateable in CI, and it produces files. `deploy` is the only thing that talks to the API.

If Argo CD is adopted: `config_render` renders and commits, `deploy` is unplugged, **nothing else moves**. That is why these two roles must never be merged, even when merging would be shorter.

---

## Le typage YAML, et pourquoi il mord / YAML typing, and why it bites

**FR** — YAML transforme `yes`, `no`, `on`, `off`, `true` en booléens Python. WAS attend les **chaînes** `"true"` et `"false"` pour la plupart des propriétés personnalisées. Un port écrit `08080` devient de l'octal ; une version écrite `9.0` devient un flottant.

Le dépôt source s'en protégeait par des guillemets posés à la main — donc par discipline. Ici, `argument_spec` avec `type` et `choices` valide **à la frontière**, et `.yamllint` autorise explicitement les chaînes `"true"`/`"false"` pour que le linter ne pousse pas à les déquoter.

Cas réel relevé dans `grp_was_90.yml` du dépôt source : la clé `verifVersionSdk:` est vide, vaut donc `None`, et partout où `{{ verifVersionSdk }}` était utilisé la chaîne `"None"` était rendue. Avec une approche `shell:`, personne ne le signale jamais.

**EN** — YAML turns `yes`, `no`, `on`, `off`, `true` into Python booleans. WAS expects the literal **strings** `"true"` and `"false"` for most custom properties. A port written `08080` becomes octal; a version written `9.0` becomes a float.

The source repository guarded against this with hand-placed quotes, i.e. by discipline. Here, `argument_spec` with `type` and `choices` validates **at the boundary**, and `.yamllint` explicitly allows the `"true"`/`"false"` strings so the linter does not push anyone to unquote them.

A real case found in the source repository's `grp_was_90.yml`: the key `verifVersionSdk:` is empty, therefore `None`, and everywhere `{{ verifVersionSdk }}` was used the string `"None"` was rendered. With a `shell:`-based approach, nothing ever reports it.

---

## Chiffres relevés sur le dépôt source / Figures measured on the source repository

Inspection directe des sept archives de `github.com/CGA71/WAS`. Ils sont cités dans le README et servent de base d'estimation.

Direct inspection of the seven archives in `github.com/CGA71/WAS`. These are quoted in the README and used as the estimation base.

| | |
|---|---|
| Scripts Jython / Jython scripts | 86, dont 33 `*Exist.py` |
| Types de ressources `wsadmin_*` | 34 |
| Suppressions réellement implémentées / deletions actually implemented | **5** sur 34 annoncées |
| Playbooks `pbk_*` | 14 |
| Types de ressources SIBus | 6 (+ `pbk_dmgr_creation_sibus.yml`) |
| Appels `AdminApp.install` | **0** — le déploiement war/ear n'existe pas |
| Occurrences de « AIX » | **0** |
| Manifests Kubernetes écrits à la main | 463 |
| `Secret` Kubernetes avec `data:` renseigné | **58**, dont `PRD/` |
| Keystores `.p12` versionnés | 14 |
