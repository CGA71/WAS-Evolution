# `group_vars` — what goes where

| File | Scope | Contents |
|---|---|---|
| `all/*.yml` | every host, every environment | site facts, paths, install directories, runtime defaults |
| `dmgr.yml`, `nodeagents.yml` | a role group | what the machine does, never where it lives |
| `<environment>.yml` | one environment | **only what differs from `all/`** |

## Per-environment files

The file name is the environment group name from `hosts.yml`, which is the
survey answer in lowercase. There is no list of valid names in the collection:
create the group, create the file, and it is picked up.

These files used to be named after a former client's four environments — an
environment nomenclature carried over from elsewhere, which has no place in
this repository. The template below replaces them.

```yaml
---
# <code>. Only what differs from group_vars/all.
# Everything else is inherited, or derived from was_environment.

# Port base, offset per environment so two can share a host during a
# migration.
was_base_port: 31000

# Declared production? The collection cannot infer it: the environment value
# is open, so no code can know which codes this site calls production. With
# prod, the model role refuses to run without -e model_allow_production=true,
# and the AWX workflow carries an Approval Node for the same intent.
was_environment_tier: prod

# Optional. Reports only, and defaults to the code itself.
was_environment_long_name: "User acceptance"

# Optional. The letter that appears inside the deployment manager node name,
# defaulting to the first letter of the code. Declare it only where a site
# naming standard says something else.
was_environment_letter: U
```

## Moving one environment along the trajectory

Three values, and the model role refuses an unsupported pair — traditional
cannot go past Java 8, and `liberty_ocp` refuses IBM Java 8 because its only
image variant is the retired UBI Standard.

```yaml
runtime:
  product: liberty_more
  jdk:
    version: 21
    vm: openj9

liberty_features:
  - javaee-8.0
  - monitor-1.0
```

## Overriding one artefact, not the list

An environment that is deliberately a fixpack behind declares the entries that
differ; they are merged recursively over `was_ibm_artifacts_common`. This is
why the artefacts are a dictionary rather than twenty flat variables — a flat
override would mean carrying a whole copy of the list.

```yaml
was_ibm_artifacts_override:
  was_nd_fixpack:
    package: com.ibm.websphere.ND.v90_9.0.7.20171222_1206
    repository: "{{ _ibm_repo }}/install_was90/fixes/9.0.0-WS-WAS-FP007"
    verify_version: "9.0.0.7"
```

## What never goes in a per-environment file

Object names. The cell, the profiles, the nodes, the cluster, its JVM members
and the shared class cache are all composed by
`roles/model/vars/naming.yml` from the environment and the channel. Override a
name here only when this site's standard genuinely differs from the pattern —
the role honours what is already defined and never overwrites it.
