# WAS Evolution

**Ansible automation for IBM WebSphere Application Server ND and WebSphere Liberty, with a three-phase trajectory to OpenShift.**

**Automatisation Ansible d'IBM WebSphere Application Server ND et de WebSphere Liberty, avec une trajectoire en trois phases vers OpenShift.**

---

| | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| **Runtime** | WAS ND 9.0 traditional | WebSphere Liberty | WebSphere Liberty |
| **JDK** | IBM SDK Java 8 | Semeru 21 (OpenJ9) | Semeru 21+ |
| **Platform / Plateforme** | AIX / RHEL | AIX / RHEL — *same machines* | OpenShift / RHCOS |
| **Admin plane / Plan d'admin** | wsadmin modules | wsadmin modules (MoRE) | render + `kubernetes.core` |
| **Waves / Vagues** | 0 – 1 | 2 – 3 | 4 – 5 – 6 |

Each phase is a **stable, production-grade state**, not a transit point. The programme can stop at the end of any phase and leave a coherent, supported estate.

Chaque phase est un **état stable et exploitable en production**, pas un point de passage. Le programme peut s'arrêter à la fin de l'une d'elles et laisser un parc cohérent et supporté.

---

**Jump to / Aller à :** [English](#english) · [Français](#français)

---

<a name="english"></a>

# English

## 1. What this is

A single Ansible collection that administers the whole WebSphere estate — traditional WAS ND today, Liberty on OpenShift tomorrow — from one source of truth.

It replaces an existing body of work (roughly 800 files, 86 Jython scripts, 34 `wsadmin_*` task files, 4 shell launch scripts) that no longer runs on a current `ansible-core` and whose idempotency is simulated by marker files.

### Design decisions

| Subject | Decision | Reason |
|---|---|---|
| Deliverable form | An **Ansible collection**, not a role folder | The only format an Execution Environment loads; FQCN removes the symlink workaround |
| Traditional plane | **Modules** driving a single Jython driver | wsadmin is imperative: idempotency, `--check` and `--diff` must be built |
| Liberty / OpenShift plane | **No modules** — `kubernetes.core` + the Liberty operator CRD | Kubernetes already reconciles. Writing Liberty modules would re-implement `kubernetes.core`, worse |
| Source of truth | **One shared YAML model**, two render back-ends | Migration becomes a back-end switch instead of an inventory rewrite |
| Inventory | **All YAML** | The configuration plane carries nested structures INI cannot express |
| OpenShift convergence | **Ansible applies** to start; GitOps boundary preserved | `config_render` and `deploy` stay separate roles, so adopting Argo CD later costs nothing |

### The guiding principle

The traditional plane and the Liberty plane share almost no automation mechanics. They share a *configuration intent*. This architecture isolates that intent in one layer and accepts two frankly dissimilar back-ends underneath. Any attempt to make one resemble the other fails.

## 2. Architecture

```
LAYER 1 — SOURCE OF TRUTH
  Product-agnostic YAML model: datasources, JDBC providers, J2C aliases,
  JVM properties (as intents, not flags), applications, keystores, security.
  About 40% of the scope, genuinely common. Schema-validated before any render.
        |
        +-----------------------+-----------------------+
        v                       v                       v
LAYER 2a                  LAYER 2b                 LAYER 2c
TRADITIONAL               LIBERTY ON OPENSHIFT      LIBERTY MANAGED (MoRE)
modules -> Jython         model -> server.xml       ND 9.0.5.23+ drives
driver -> wsadmin         -> ConfigMap -> CRD        Liberty from the cell,
one JVM launch per        applied by                 console + wsadmin + JMX
batch                     kubernetes.core            (the migration bridge)
        |                       |                       |
        +-----------------------+-----------------------+
        v
LAYER 3 — ORCHESTRATION
  Ansible Automation Platform: Workflow Templates, Surveys, Approval Nodes,
  typed Credentials, environment-to-environment promotion, smoke tests.
```

### Why the Liberty plane has no modules

`was_*` modules exist because wsadmin is imperative and idempotency has to be manufactured. On OpenShift, `kubernetes.core.k8s` already does check-then-change with a real `changed` and a real `--diff` through server-side apply.

### The limit, acknowledged up front

Do not unify more than is actually unified. The overlap is real for datasources, JVM properties, application bindings and security. It is **nil** for cells, profiles, nodeagents, server templates, SIBus and IHS on one side; for `replicas`, probes, quotas, Routes and `featureManager` on the other. The model therefore has one common section and two product-specific sections. False symmetry is what kills these projects.

## 3. Repository layout

```
ansible_collections/wasevo/websphere/
  plugins/
    module_utils/wsadmin.py      launch, JSON parsing, no_log
    modules/                     TRADITIONAL plane only
    jython/
      driver.py                  single wsadmin entry point
      handlers/                  read() / write() per resource type
  roles/
    model/                       schema validation + JVM translation table
    traditional/                 prereqs_os (RHEL + AIX), installation_manager,
                                 was_install, was_fixpack, was_sdk,
                                 profile_dmgr, profile_nodeagent, server_member,
                                 ihs, config, audit
    liberty/
      config_render/             model -> server.xml — NO cluster access
      image_build/               Dockerfile or S2I, tag, registry push
      deploy/                    CRD + ConfigMap + Secret via kubernetes.core
      verify/                    k8s_info + smoke test
  playbooks/
inventories/                     one all-YAML inventory; the environment is an input
model/                           the shared declarative model
docs/                            architecture and per-phase notes
ci/
  k3s/                           simulation pods, the lab VM, RBAC,
                                 make-lab-vm.sh, lab-mirror-was.sh
  awx/                           the AWX operator and its kustomizations
```

**Never merge `config_render` and `deploy`.** `config_render` does not touch the cluster: it runs offline, is testable without OpenShift, and is the GitOps boundary. If Argo CD is adopted, `config_render` renders and commits, `deploy` is unplugged, nothing else changes.

## 4. Product × JDK matrix

| | IBM SDK Java 8 | Semeru 17 | Semeru 21 | Semeru 25 |
|---|---|---|---|---|
| **WAS ND 9.0 traditional** | only supported option | no | no | no |
| **Liberty managed (MoRE)** | diagnostic only | yes (EOS 10/2027) | ND >= 9.0.5.25 | ND >= 9.0.5.29 |
| **Liberty on OpenShift** | ruled out (UBI Standard) | yes | **target** | yes |

Traditional WAS ND 9.0 is locked to IBM SDK Java Technology Edition 8. Java 17 and 21 are not available on the traditional engine; they are reachable only through Liberty. **The JDK dimension is therefore not orthogonal to the product dimension** — `roles/model` enforces this at render time, not on the live cell.

### Two consequences for the trajectory

1. **The JDK jump cannot happen before Liberty.** The traditional engine does not go past Java 8.
2. **It must not happen after containerisation either.** That would mean building a Liberty image on IBM Java 8, i.e. on UBI Standard — the variant IBM retires after Liberty 26.0.0.12. Phase 2 is the only place this change belongs.

### "OpenJDK 21" means OpenJ9 here

Official WebSphere Liberty images on `icr.io/appcafe` ship **IBM Semeru Runtime, therefore OpenJ9**, for Java 8, 11, 17, 21 and 25. There is no HotSpot/Temurin variant in the official set. This is good news: the existing JVM tuning is heavily J9-specific and largely survives. On Temurin, `-Xgcpolicy`, `-Xmns`/`-Xmnx`, `-Xshareclasses`, `-Xdisableexplicitgc` and `-Xverbosegclog` do not: the JVM refuses to start on an unknown `-X`, or silently drops GC logging, which is worse. **Stay on IBM images, or redo the tuning entirely.**

## 5. Phase 1 — WAS traditional + IBM JDK 8

> **Target state:** the current estate, made idempotent, auditable and replayable.
> **This phase pays for itself even if no application ever migrates.**

### Wave 0 — Foundation (nothing changes in production)

**Actions**

1. Create the collection skeleton, `galaxy.yml`, `meta/runtime.yml`.
2. Write `module_utils/wsadmin.py`: launch, 0600 payload file, JSON parsing, `no_log`.
3. Write `plugins/jython/driver.py`: one wsadmin entry point, dispatching to handlers, returning JSON on stdout.
4. Write the `was_cluster` pilot module plus its `handlers/cluster.py` (`read()` / `write()`).
5. Write `roles/model`: schema validation and the JVM flag translation table.
6. Write `roles/liberty/config_render` with the `server.xml`, `jvm.options` and `server.env` templates.
7. Build the two Execution Environments: `ee-was-traditional` and `ee-liberty-ocp`.
8. Create the AAP project, two inventories, the Credential types, the first Workflow Template.
9. Rebuild the first non-production environment with the new tooling, feature-for-feature.
10. Render the pilot datasource, declared once, into the three trajectory couples.

**Entry criteria** — GitLab repository, AAP reachable, a non-production cell available for rebuild.

**Exit criteria** — that cell rebuilt end to end from AAP; `--check` and `--diff` demonstrated on a real change; the three renders of the pilot datasource agree.

**Rollback** — the legacy `launch_*.sh` scripts remain runnable in parallel.

### Wave 1 — Industrialising the traditional plane

**Actions**

1. Port the 34 `wsadmin_*` resource types to modules, prioritised by **actual usage frequency**, not alphabetically.
2. Implement the ~29 missing deletions. `state: absent` is advertised on 34 types and implemented on 5; `clusterDestroy` is commented out.
3. Create `was_application` for war/ear deploy, update and remove. This does not exist today: there is not a single `AdminApp.install` call in the source repository.
4. Remove the password from the command line everywhere — module argument with `no_log: true`, or `soap.client.props`.
5. Add AIX support to `prereqs_os`. There is currently zero AIX reference in the source repository.
6. Drop RedHat 5 and 6 from the OS prerequisites.
7. Split the variables: environment-specific stays in the inventory, product-specific becomes role `defaults/`.
8. Write `roles/traditional/audit`, runnable in `--check --diff`, producing the gap between declared and live state.
9. Convert the 4 `launch_*.sh` scripts into Workflow Templates with Surveys and Approval Nodes.

**Entry criteria** — wave 0 exit criteria met.

**Exit criteria** — any cell replayable without side effects; drift detected and displayable; application deployment automated; no secret on a command line or in a log.

**Rollback** — per module; the legacy task files stay in git history.

## 6. Phase 2 — Liberty + OpenJDK 21 and later

> **Target state:** Liberty and Semeru 21 on the existing machines, still administered by wsadmin through MoRE.
> Runtime and JDK change together here, because section 4 leaves them nowhere else to go.

### Wave 2 — Application assessment

**Actions**

1. Run each application through IBM's Migration Toolkit (binary analysis).
2. Classify against the grid in section 8.
3. **Arbitrate the SIBus question.** Six SIBus resource types in the source repository signal real use of embedded messaging. Liberty has no built-in messaging engine: an external broker is required (MQ, Artemis, Kafka). This is an application architecture decision, not an infrastructure one.
4. Confirm the open verification point in section 9 before committing to any schedule.
5. Produce the ordered backlog, with estimated effort and named blocking dependencies.

**Entry criteria** — phase 1 complete; development teams available, not just operations.

**Exit criteria** — every application in one of four categories, with effort and blockers named.

### Wave 3 — Liberty and Semeru 21 in place

**Actions**

1. Pick two or three **category A** applications only.
2. Render `server.xml`, `jvm.options` and `server.env` from the shared model via `config_render`.
3. Apply the JVM flag translation table: GC policy, nursery, shared class cache, dumps, GC log.
4. Switch monitoring to `monitor-1.0` / MicroProfile Metrics. **PMI does not exist on Liberty** — this must be ready now, not in phase 3.
5. Deploy Liberty on the existing machines, under `liberty_more` or standalone.
6. Cut over and back through the IHS plugin.
7. Observe, then repeat for the next applications.

**Diagnostic step** — if an application does not start, re-run the **same** `server.xml` under IBM Java 8 to separate a runtime problem from a JDK problem. **On machines only, never as an image.** Abandon the step as soon as the diagnosis is made.

**Entry criteria** — application classified A; monitoring replacement ready.

**Exit criteria** — application running on Liberty + Semeru 21; JVM tuning translated and verified.

**Rollback** — the original WAS ND cell is untouched; cut back via the IHS plugin.

## 7. Phase 3 — OpenShift + Liberty + OpenJDK 21 and later

> **Target state:** the same Liberty configuration and the same JDK, now an immutable image driven by the operator CRD.

### Wave 4 — Containerisation (packaging changes, configuration does not)

**Actions**

1. Build the image on `kernel-java21-openj9-ubi-minimal`, or `ubi-micro` where the Liberty version allows it (26.0.0.9+). Prefer `kernel` and declare features explicitly in `server.xml`.
2. Replace the fixed `-Xmx` with `-XX:MaxRAMPercentage`. **A fixed `-Xmx` against a pod memory limit is a guaranteed OOMKilled.**
3. Point the dump directories at a persistent volume.
4. Point the shared class cache at a volume, or it is rebuilt on every start.
5. Redirect the GC log away from the container filesystem.
6. Run the image locally or on a trial container host.

**Entry criteria** — wave 3 exit criteria met for the application concerned.

**Exit criteria** — image starts with the model-rendered configuration, no fixed `-Xmx`, dumps persisted, GC log reachable.

**Proof** — the same model and the same JDK produce the wave 3 configuration on machines and the wave 4 configuration in an image. If the two diverge, the defect is in the render, not in the application.

### Wave 5 — OpenShift (platform changes, nothing else)

**Actions**

1. Deploy via the `WebSphereLibertyApplication` custom resource (`OpenLibertyApplication` for Open Liberty). One resource replaces Deployment, Service, Route, ServiceAccount and probes.
2. Render ConfigMap and Secret; source secrets from an AAP Credential or the External Secrets Operator — **never from a versioned file**.
3. Configure Route, liveness and readiness probes, requests and limits.
4. Set up dumps and traces via `WebSphereLibertyDump` and `WebSphereLibertyTrace`.
5. Wire Prometheus to the metrics exposed in wave 3.
6. Build the promotion workflow: `render -> build -> push -> [Approval] -> first environment -> smoke -> [Approval] -> next -> ... -> production`.

**Entry criteria** — wave 4 exit criteria met.

**Exit criteria** — application in production on OpenShift; rollback by rollout.

**Note** — runtime, JDK and image are already frozen and proven from waves 3 and 4. That is the whole point of this ordering.

### Wave 6 — Decommissioning

**Actions**

1. Remove migrated servers, clusters and nodes. **This is only possible thanks to the ~29 deletions created in wave 1.**
2. Reduce the IHS footprint.
3. Release licences.
4. Keep the residual traditional estate under the same collection.

**Exit criteria** — traditional scope reduced to what cannot migrate, still automated by one tool.

## 8. Application classification

| Category | Criteria | Trajectory |
|---|---|---|
| **A — Direct lift** | Java EE 7 or below, no SIBus, no proprietary WebSphere API, no JAX-RPC, no remote EJB, state in session only, no local filesystem dependency | Waves 3 → 4 → 5 with no code change. **Start here** |
| **B — Lift with adjustments** | Shared libraries, isolated classloaders, WorkManagers, startup beans, XA transactions, WS-Security | Wave 3 after reconfiguration. Moderate effort, concentrated in configuration |
| **C — Blocking dependency** | **SIBus** and embedded messaging, complex WS-Security policy sets, PMI consumed by monitoring, admin console dependency | Architecture decision first. Do not start before the broker is arbitrated |
| **D — `javax` → `jakarta`** | Targeting Jakarta EE 10+, namespace change | Partial rewrite. An application project, not an infrastructure one |

**Sequencing rule** — take two or three category A applications all the way through wave 5 before starting anything in B. The goal is not speed: it is to push one real case through the entire chain (model, render, image, CRD, monitoring, promotion). Chain defects surface on the first application, so make it a simple one.

## 9. Open verification point

> **`javaee-8.0` on Semeru 21.**
>
> This is the assumption holding up phase 2 for category A applications — the ones specifically chosen not to be rewritten. Liberty features carry Java level requirements. If this couple is not supported on the chosen Liberty version, the `javax` → `jakarta` migration becomes mandatory for everyone, and the scope of the programme changes radically.
>
> **Confirm this before committing to any schedule.** It is not confirmed in the IBM documents consulted so far.

## 10. Functional gaps — what must be replaced, not migrated

| WAS ND function | Present in source repo | On Liberty | Action |
|---|---|---|---|
| **SIBus / embedded messaging** | 6 `wsadmin_sibus*` types + `pbk_dmgr_creation_sibus.yml` | no equivalent | External broker. Application architecture decision |
| **WS-Security policy sets** | `createWSSecurityPolicy.py`, 6 binding XML files | different model | `wsSecurity-1.1` feature, configuration rewritten |
| **PMI monitoring** | `pmiConfig`, `pmiModuleConfig`, `-XrunpmiJvmtiProfiler` | does not exist | `monitor-1.0`, MicroProfile Metrics, Prometheus |
| **javacore / heapdump collection** | `SearchFile.ksh` + 15-minute cron, dedicated `/app/dump/was` | to rebuild | PVC, or `WebSphereLibertyDump` CR |
| **Session replication (DRS)** | implicit in clusters | different model | `sessionCache` (JCache: Infinispan, Hazelcast) or sticky routing |
| **Virtual hosts** | `wsadmin_virtualhost`, `wsadmin_virtualhostAlias` | concept absent | OpenShift Routes. The notion disappears |
| **IHS, plugin, propagation** | full IHS role, `propagatePlugin.py` | not applicable | Route / Ingress. The IHS role stays useful for the residual estate |
| **Shared libraries** | `wsadmin_sharedLibrary` | supported | `<library>` and `<classloader>` in `server.xml` |
| **Datasources, JDBC, J2C** | 7 resource types, 5 bundled drivers | supported | Core of layer 1. Renders in both back-ends |

## 11. Running it

```bash
COL=ansible_collections/wasevo/websphere/playbooks

# install dependencies
ansible-galaxy collection install -r collections/requirements.yml

# render the pilot datasource in all three trajectory couples. No inventory -
# the play is on localhost - but the environment is still an input: the model
# names every object it renders
ansible-playbook $COL/pilot_render_matrix.yml -e was_environment=PILOT

# validate one environment - the environment is a launch input, not a
# directory, so it is passed even for a validation that touches nothing
ansible-playbook -i inventories/was $COL/model_validate.yml -e was_environment=RA

# traditional plane, dry run first - always
ansible-playbook -i inventories/was $COL/traditional_config.yml   -e was_environment=<code> --check --diff

# or one step at a time: each of these is replayable on its own, which is one
# wsadmin session instead of the whole chain. See section 18.
ansible-playbook -i inventories/was $COL/traditional_cluster.yml   -e was_environment=<code> --check --diff
ansible-playbook -i inventories/was $COL/traditional_cluster_members.yml   -e was_environment=<code> -e was_cluster_members_per_node=2

# In AWX none of these flags are typed: the Survey asks for the environment,
# the channel, the application servers per node and the production
# acknowledgement.
```

### Execution Environments

| EE | Contents | Target |
|---|---|---|
| `ee-was-traditional` | `ansible-core` + this collection. **No Java, no Jython** — the driver ships to the target and runs in the target's own wsadmin | WAS ND, AIX and RHEL |
| `ee-liberty-ocp` | `ansible-core` + `kubernetes.core` + `redhat.openshift` + the `kubernetes` Python library | Liberty on OpenShift |

### AAP notes

- **The Liberty plane's inventory is `localhost`.** Nothing is connected to: the job runs in the EE and talks to the OpenShift API.
- **Workflow nodes do not share facts.** A value crossing two nodes — the image tag produced by the build — goes through `set_stats`.
- Set Job Template timeouts generously: a wsadmin batch takes minutes.
- `serial` stays in the playbook for ripple restarts. It is not a workflow split.

## 12. Security

This repository is **public on the internal GitLab for now**, deliberately, to avoid token friction during bootstrap. It will be restricted later. Until then:

- **No secret is committed.** No keystore, no `.p12`, no `keyfile.kdb`/`.sth`, no password in an inventory.
- Secrets travel through AAP Credentials, Ansible Vault, or 0600 files — never command-line arguments.
- The source repository's exposures are **not** carried over: 58 Kubernetes `Secret` manifests with populated `data:` blocks (including `PRD/`), 14 `.p12` keystores, and `was_admin_password: "wsadmin"` / `was_keystore_password: "password"` in `group_vars`.

> **Action required on the source repository**, independently of this project: Kubernetes `Secret` base64 is not encryption. Rotate the affected database credentials, then purge the git history — deleting the file is not enough, it stays in the commits.

## 13. Risks

| Item | Nature | Handling |
|---|---|---|
| **`javaee-8.0` on Semeru 21** | scope risk — verify first | See section 9. Confirm before any schedule commitment |
| **SIBus** | structural risk | Broker arbitration before wave 2. Determines which applications migrate and in what order |
| **Porting volume** | effort risk | 34 resource types. Mechanical and parallelisable, but long. Prioritise by real usage frequency |
| **Layer 1** | architecture risk | Validated or invalidated in wave 0 on a single object rendered three ways. One day, not thirty modules later |
| **UBI Standard** | vendor deadline | Retired after Liberty 26.0.0.12. Why *Liberty + IBM JDK 8* is ruled out as a target |
| **Java SE 17** | vendor deadline | EOS October 2027 on managed Liberty. The trajectory targets 21 directly and does not stop at 17 |
| **Monitoring** | functional gap | PMI does not exist on Liberty. The switch must be ready in **wave 3**, not phase 3 |
| **Skills** | people risk | Two cultures coexisting for a long time. Layer 1 is also what lets both teams talk about the same object |

## 14. The forge and its dependencies

Every dependency the forge needs is declared in one place,
`roles/forge_preflight/defaults/main.yml`, and verified by the `forge_preflight`
role before anything is installed. A missing dependency becomes a named
assertion failure, not a cryptic error three roles later.

The legacy repository had the opposite shape: it installed `psmisc`, which
`manageprofiles` needs for `killall`, as the **last task** of the install
playbook — after the profiles that depend on it.

| Side | Declared | Checked with |
|---|---|---|
| Control | `ansible-core` minimum, collections per plane, Python packages, PATH commands, optional image builder | `ansible_version`, `ansible-galaxy collection list`, an import test per package |
| Target (WAS/IHS) | OS packages per family including AIX, shell limits, required directories, minimum free space, the binaries share | `package_facts`, `stat`, `ansible_facts.mounts` |
| Target (OpenShift) | API groups, the Liberty operator CRD, the namespace | `kubernetes.core.k8s_info` |

Scope follows `runtime.product`: the traditional plane needs SSH and a staged
Jython driver, the Liberty plane needs an API endpoint and no SSH at all. The
two Execution Environments differ for the same reason — and `ee-was-traditional`
carries **no Java and no Jython**, because the driver is data that ships to the
target and runs in the target's own `wsadmin`.

Free space is checked before an install or a fixpack on purpose: a fixpack that
runs out of space mid-apply leaves the installation in a state that costs far
more to recover than a refused playbook.

## 15. CI: simulation on k3s

The pipeline proves three things, cheapest first.

**Static, no cluster.** `yamllint`, `ansible-lint`, syntax checks, then:
`site-vars-drift` compares the SHA-256 of `00_site.yml` across environments;
`model-matrix` validates every environment, asserts production is refused
without `-e model_allow_production=true` and passes once acknowledged, and
asserts the diagnostic JDK is refused; `pilot-render` renders one datasource for
all three phases.

**The whole traditional chain, against a fake cell, no cluster.** `stub-unit`
runs `ci/run-stub-tests.sh`, which drives the real `driver.py` and the real
cluster handler through a `wsadmin.sh` stand-in. WAS ND cannot ship in a CI
image — licensing, entitlement, several gigabytes — but almost nothing that goes
wrong in the traditional plane is WAS behaviour. It is the plumbing: argument
validation, the payload file, the launch, dispatch, read/plan/write, the JSON
answer, `changed` and `diff`. All of that runs for real. Twenty-six checks, including
two guards that fail the build if credentials ever reappear on a wsadmin command
line or the properties file is not `0600`, and one that asserts node
synchronisation fires on real changes only.

Most of those checks are the whole life of a cluster member: created, replayed,
drained to weight 0, its port pinned and the pinned port replayed, deleted,
and refused when the cluster does not exist or when two JVMs of one node would
claim the same port. The member handler is the first one to carry a **list**
rather than a single object, and it is where a shallow dict copy in the planner
silently skipped the write while the diff claimed the change had happened —
caught here, by a replay that had to report no change and did not.

**The same chain against real hosts on k3s.** Two namespaces:

| Namespace | Holds | Why separate |
|---|---|---|
| `was-sim-dmgr` | one Rocky 9 pod standing in for the deployment manager | The DMGR holds the master configuration repository and pushes it out |
| `was-sim-nodeagents` | two Rocky 9 pods standing in for node agents | A node agent receives. Different trust zone |

Rocky Linux 9 because it is the closest freely redistributable match to the RHEL
the estate runs on: same package manager, same systemd, same
`/etc/security/limits.d` semantics. The image is **stock** — no registry
dependency, nothing to keep current. Packages, the Jython driver and the wsadmin
stub are all put in place by the same roles that will run against the real
estate, so CI exercises the production staging path rather than a special one.

There is no `sshd` and no private key in those pods. Ansible reaches them with
the `kubernetes.core.kubectl` connection plugin, over `pods/exec`.

`sim:configure` runs the play three times: `--check --diff`, then apply, then
again. **The third run must report `changed=0` on every host.** That replay is
the only real proof of idempotency, and it is a claim the legacy approach could
not make — its marker files reported "nothing to do" whether or not the cell
still matched.

`sim:members` is the vertical axis and the second replay. `sim:configure` builds
one member per node, which is a horizontal cluster; this job runs
`traditional_cluster_members.yml` **on its own** — being separately launchable
is the point of splitting it out — with two members per node over two nodes,
which is four JVMs. It then asserts the shape in the role's own words, that no
two servers of a node hold the same port, that a count above the bound is
refused, and that one imposed member name against a count of two is refused
with both ways out named.

`sim:isolation` asserts the boundary rather than describing it: the CI identity
must **not** be able to exec into `kube-system`, `ci` or `default`, and the
boundary must hold - checked by **traffic**, not by reading the policy objects.
[`ci/assert-network-boundary.sh`](ci/assert-network-boundary.sh) starts a
listener on the target, then connects across the boundary: a node agent
reaches the deployment manager on the allowed port, and is refused on any
other; the deployment manager cannot reach a node agent; a node agent cannot
reach another. An existing NetworkPolicy proves a YAML object exists, not that
anything is blocked - a cluster with its policy controller off holds the same
objects and enforces nothing. And checking traffic needs only `pods/exec`,
which the CI identity already holds, so the test runs on a cluster built from
this repository with nothing granted by hand. The ServiceAccount is bound by namespaced
Roles, never a ClusterRole, so a leaked CI token reaches exactly two throwaway
namespaces.

`sim:teardown` removes the pods and leaves the namespaces: they are
infrastructure applied once, and a pipeline that deletes them makes itself
unrunnable.

## 16. The install lab: a KubeVirt VM

The simulation above installs nothing. Installation Manager needs somewhere real
to land, and that is a separate machine: **one KubeVirt VM**, `was-lab-01` in the
`was-lab` namespace, declared in
[`ci/k3s/20-was-lab-vm.yml`](ci/k3s/20-was-lab-vm.yml).

**Why a VM and not another pod.** Installation Manager writes into the
installation directories, keeps an installation registry, expects a genuine
filesystem layout and enough disk, and `manageprofiles` expects a working
process tree — it calls `killall`. A container is the wrong shape for that. The
simulation pods are stock Rocky 9 on `emptyDir`, with no `sudo` and a wsadmin
stub; nothing in them could carry a 2.5 GB IBM install. KubeVirt and CDI are
already running on the cluster, so the VM costs nothing extra to operate and is
destroyed by deleting one namespace.

| Object | Name | Note |
|---|---|---|
| Namespace | `was-lab` | |
| DataVolume | `was-lab-disk` | Rocky 9 GenericCloud imported by CDI, 40 Gi |
| VirtualMachine | `was-lab-01` | 4 vCPU, 6 Gi — WAS 9.0 wants 2 Gi minimum and is miserable there |
| Service | `was-lab-01` | `22`, `9043`, `9080`, reachable in-cluster without a Route |
| Secret | `was-lab-cloudinit` | cloud-init user data. **Not in this repository**: it carries the SSH public key |

Bring it up with [`ci/k3s/make-lab-vm.sh`](ci/k3s/make-lab-vm.sh), which builds
the Secret from the key pair on the node, applies the manifest, waits for the
image import and prints the address. Teardown is `kubectl delete ns was-lab`,
and it leaves nothing behind.

### Getting in

**The VM runs inside a pod, and that pod is not the way in.** KubeVirt wraps it
in `virt-launcher-was-lab-01-xxxxx`; `kubectl exec` on that pod lands in the
virt-launcher container, next to the QEMU process, not in the Rocky guest.
Installation Manager is unreachable by that route.

```bash
# On a k3s node /usr/local/bin/kubectl is a SYMLINK TO k3s, and that wrapper
# reads /etc/rancher/k3s/k3s.yaml - root-owned, mode 0600 - unless KUBECONFIG
# says otherwise. Without this line kubectl fails with a permission error that
# reads like a broken cluster, the command substitution below returns empty,
# and every command after it silently runs on the node instead of the VM.
export KUBECONFIG=$HOME/.kube/config

kubectl -n was-lab get vmi,pod          # vmi was-lab-01 must be Running

IP=$(kubectl -n was-lab get vmi was-lab-01 -o jsonpath='{.status.interfaces[0].ipAddress}')
[ -n "$IP" ] || echo "no address - do not run anything else"
ssh -i ~/.ssh/was_lab ansible@"$IP"
```

`virtctl` would avoid the address lookup entirely, but it is **not installed on
this node** - only `kubectl` and `k3s` are. `virtctl console` would be of no use
anyway: cloud-init sets `ssh_pwauth: false`, `disable_root: true` and no
password at all. The key is the only way in.

AWX job pods run inside the cluster, so `was-lab-01.was-lab.svc.cluster.local`
resolves and the inventory uses that name. From the node itself, pass
`-e ansible_host=$IP`.

### The media, which nothing downloads

Neither artefact can be fetched without an IBMid, so both are staged by hand.
In the lab inventory the globs are **on the controller** and the roles copy the
archives across; in the estate the media arrives on a mounted share and the
globs stay empty.

| Artefact | Controller glob (`group_vars/was_lab.yml`) | Where it lands on the VM |
|---|---|---|
| Installation Manager | `/mnt/binaries/IBM/install_im/*.zip` | `/mnt/binaries/IBM/install_im` |
| WAS 9.0 for Developers | `/mnt/binaries/IBM/install_was90/*.zip` | `/mnt/binaries/IBM/install_was90` |
| Fix packs | `/mnt/binaries/IBM/fixes/*.zip` | one repository directory per archive |

Each fix pack archive is one Installation Manager repository and they must not
be unpacked on top of each other: two `repository.config` files in one directory
and `imcl` reads whichever it finds first. Under AWX the controller is the job
pod, so these paths have to be mounted into the Execution Environment or the
staging step finds nothing.

The base Developers install yields **9.0.0.0**. The 9.0.5.x level comes from the
fix pack, which is a separate job — hence `was_expected_version: "9.0.0.0"`.

### Filling the local repository from IBM

The 9.0.0.0 zips are not the only route in. The live ILAN composite repository
serves the **current** level, so Packaging Utility can mirror 9.0.5.x straight
into the media directory, after which the VM never needs the internet again.
[`ci/k3s/lab-mirror-was.sh`](ci/k3s/lab-mirror-was.sh) does exactly that, run
from the node like `make-lab-vm.sh`:

```bash
bash ci/k3s/lab-mirror-was.sh --check    # preconditions only, changes nothing
bash ci/k3s/lab-mirror-was.sh            # the whole thing
```

It verifies `KUBECONFIG`, the VMI phase, the key, passwordless sudo, the
Installation Manager version, free space and egress **before** asking for
anything. Then it prompts once for the IBMid through `imcl -prompt` — the
mechanism Installation Manager itself recommends when it refuses a repository —
which writes an encrypted credential store on the VM. No later run carries a
secret, and the password never appears on a command line or in shell history.

That interactive prompt is why this is a script and not a playbook: it needs a
TTY, and an AWX job pod has none.

Two things to know. ILAN is the licence the "for Developers" edition ships
under; IBM's table has no entry called "Developers", so the composite is
`V9WASILAN` and the individual repository is `com.ibm.websphere.ILAN.v90`. And a
mirror taken from the live repository is **9.0.5.x, not 9.0.0.0** — so
`was_expected_version` has to move with it, or the install job's closing assert
fails on a perfectly good install.

### Installation Manager on the VM

The install role runs `imcl` with `become`, so this is an **administrator
installation**: the binary is root-owned and `imcl` as the service account
fails with `CRIMC1018E ERROR: Administrator privileges are required`. Only
`version` works without privileges. Everything else needs `sudo`:

```bash
IMCL=/app/binaries/InstallationManager/eclipse/tools/imcl

$IMCL version                                       # the one call that needs nothing
sudo $IMCL listInstalledPackages -long
sudo $IMCL listAvailablePackages -repositories /mnt/binaries/IBM/install_was90 -long
sudo $IMCL -c                                       # console mode
```

The agent data and the installation registry are under `/app/data/IM/agentdata`,
not `/var/ibm/InstallationManager`, because the role passes `-dataLocation`. One
mount therefore holds the whole installation.

**There is no browser route.** Installation Manager has no web interface;
`IBMIM` needs an X server, and the `ibm.com/software/repositorymanager/...`
service repository URLs do not load in a browser either — they are consumable
only by Installation Manager. A local repository *can* be served over HTTP by
any web server and handed to `imcl` as
`http://host/repo/repository.config`, which is the only place a browser has in
this picture.

The same query without opening a shell, which is also how AWX runs it:

```bash
ansible -i inventories/lab was_lab -m command \
  -a "/app/binaries/InstallationManager/eclipse/tools/imcl \
      listAvailablePackages -repositories /mnt/binaries/IBM/install_was90 -long"
```

The offering id is never hardcoded. The editions differ only by that id —
`com.ibm.websphere.ND.v90`, `.BASE.v90`, `.DEVELOPERS.v90` — and guessing it
produces an `imcl` error that reads like a licence problem, so the role asks the
repository what it contains.

### The workflow

| Node | Playbook | What it does |
|---|---|---|
| 1 | `lab_install_im.yml` | Installation Manager. Job 2 runs only if this succeeds |
| 2 | `lab_apply_fixpacks.yml` | pass 1 — brings Installation Manager to the level WAS needs |
| 3 | `lab_install_was.yml` | WAS for Developers and the SDK, in one `imcl` call |
| 4 | `lab_apply_fixpacks.yml` | pass 2 — patches what node 3 just installed |
| 5 | `lab_create_profiles.yml` | the profiles — deployment manager, then the federated node |
| 6 | `traditional_cluster.yml` | the cluster |
| 7 | `traditional_cluster_members.yml` | the application servers in it, vertical or horizontal |

Nodes 6 and 7 are two job templates rather than one because each of them is
replayable on its own — see section 18. On the lab they are launched with
`-e config_dmgr_hosts=dmgr`, since this inventory declares no environment
group.

One job template, two workflow nodes for the fix packs. That only works because
the role **discovers** what is installed rather than being handed a list: on
pass 1 only Installation Manager is there, on pass 2 everything is. Finding no
fix pack repository is a normal outcome — the job says what it found, says where
to put media, and exits green.

Job 3 checks for `imcl` itself rather than trusting node 1: a job template can
be launched on its own, and the failure should name what is missing instead of
dying inside a shell call.

## 17. WAS object naming is an input, not a convention

**Every name a cell is built from is a variable you set.** The cell, the
cluster, the application server, the node agent node, the deployment manager
profile: each is declared either in the inventory or answered in the AWX
survey. The repository composes a name only when nobody supplied one, and the
composed form is a fallback, never a rule.

| Variable | Names | Fallback pattern |
|---|---|---|
| `was_cell_name` | the cell | `{{ was_channel_name }}_{{ was_env_upper }}` |
| `was_cluster_name` | the cluster | `Cluster{{ was_channel_upper[:3] }}` |
| `was_cluster_member_name` | the application server JVM | cluster + node + index |
| `was_node_name` | the node — dmgr or node agent, per host | `{{ was_host_short }}Node` for an agent |
| `was_dmgr_profile_name` | the deployment manager profile | `Dmgr_{{ was_env_upper }}_{{ was_channel_name }}` |
| `was_profile_name` | the profile on this host | the dmgr pattern, or `AppSrv01` |
| `was_console_label` | the administrative console label | `{{ was_channel_name }} {{ was_env_upper }}` |
| `was_jvm_shared_class_cache` | `-Xshareclasses:name=` | `{{ was_env_upper }}%g` |

### Where to set them

Precedence runs from strongest to weakest, and Ansible enforces it:

1. **AWX survey answer**, or `-e` on the command line. Extra vars outrank
   everything, so a survey question for the cluster name is honoured whatever
   the inventory says.
2. **`host_vars/<host>.yml`** for one machine — a node whose name does not
   follow the site rule.
3. **`group_vars/<group>.yml`** for a rule — `nodeagents.yml` for every agent,
   an environment group for one environment.
4. **The pattern** in [`roles/model/vars/naming.yml`](ansible_collections/wasevo/websphere/roles/model/vars/naming.yml),
   reached only when the three above are silent.

The mechanism is one line per name in
[`roles/model/tasks/naming.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/naming.yml):

```yaml
was_cluster_name: "{{ was_cluster_name | default(was_cluster_name_pattern, true) }}"
```

`set_fact` outranks `group_vars`, so without that `default()` this task would
silently overwrite a deliberate override — the exact bug where an inventory
entry is ignored and nobody notices until the object exists under the wrong
name. Every published name is then asserted non-empty and whitespace-free,
because `wsadmin` accepts a bad name at creation and every later lookup by name
misses.

**Nothing else in the repository composes a WAS object name.** These patterns
used to live in three inventories, written out three times, with the cluster
name hardcoded to `ClusterEXT` in two of them. Three copies of a naming rule is
three chances to disagree, and the disagreement surfaces as a cell that will
not federate.

### One machine, two roles: how the lab declares an ND cell

An ND cell is a deployment manager plus at least one federated node. The lab
owns one VM, so both profiles land on it. Ansible expresses "one machine
playing two roles" with **two inventory entries** pointing at the same
`ansible_host` — not with one entry in two groups, which is the obvious
shortcut and does not work here.

| Entry | Group | What it carries |
|---|---|---|
| `was-lab-01` | `was_lab` | the installation — IM, WAS, the fix packs. Once only: `imcl` takes a lock |
| `was-lab-01-dmgr` | `dmgr` | the deployment manager profile |
| `was-lab-01-node` | `nodeagents` | the managed profile — so the node agent, and the cluster member, which is the application server |

Why not one entry in both groups:

- [`roles/model/tasks/naming.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/naming.yml)
  decides the profile name and the node name from group membership. A host in
  `dmgr` **and** `nodeagents` is a deployment manager as far as that decision
  goes, so the federated profile would be named after the deployment manager
  and federation would fail on a node name already present in the cell.
- `group_vars/dmgr.yml` and `group_vars/nodeagents.yml` both set
  `was_profile_path` and `was_service_name`. On a host in both groups one
  silently wins by alphabetical group order.

**Two port bases, for the same reason.** Each `manageprofiles` template
allocates a dozen or so ports upward from the base it is given, so one base for
two profiles on one machine means two profiles claiming the same ports.
`group_vars/all/40_runtime.yml` declares `was_lab_dmgr_base_port` (30000) and
`was_lab_node_base_port` (30100), and each role group consumes one.
`was_dmgr_soap_port` is **anchored on the deployment manager's base** rather
than on `was_base_port`, which now differs per role — otherwise a federated
node would look for the deployment manager's SOAP port 100 ports too high. It
is only a fallback either way: `profile_dmgr` reads the created profile and
publishes `was_dmgr_soap_port_actual`, which `profile_nodeagent` prefers.

Where each name is written, for the lab:

| Name | File |
|---|---|
| cell, cluster | `inventories/lab/group_vars/all/30_naming.yml` — both are cell-wide |
| dmgr profile and node | `inventories/lab/group_vars/dmgr.yml` |
| profile, node, cluster member | `inventories/lab/group_vars/nodeagents.yml` |

No environment code is written in any of them: `was_env_upper` and
`was_channel_name` are published by the `model` role from the survey answers,
and a `group_vars` template resolves when it is read, which is after that.
**Mind the precedence**: a survey answer is an extra var and outranks these
files, and an optional question left blank arrives as an empty string, which
`default(..., true)` turns back into the **role pattern** — not into the
inventory value. So a run launched from the survey either fills those questions
with the same values, or accepts the patterns.

### Standalone or ND: the topology is answered, and it decides the profile

**The installed binaries are identical either way.** The same offering, the same
installation directory, the same `imcl` line. What differs is the template
`manageprofiles` is pointed at, which is why the topology is a question on the
profile job and not on the install job - putting it on the install form would
be a decoration that changes nothing.

| `was_topology` | Template | Produces |
|---|---|---|
| `standalone` | `profileTemplates/default` | one cell, one node, its own administrative console. No deployment manager, no node agent, **no cluster** |
| `nd` | `profileTemplates/management` + `serverType=DEPLOYMENT_MANAGER` | the deployment manager |
| `nd` | `profileTemplates/managed` | a federated node, which is what gives a node agent |

[`roles/model/tasks/topology.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/topology.yml)
refuses anything other than those two values, says what each one builds, and
publishes `was_can_cluster: false` for standalone - so a cluster job refuses
early instead of failing inside `wsadmin`.

It is answered rather than derived from the inventory shape on purpose: a
single host can legitimately be a standalone server **or** a one-node ND cell.
That is an intention, and an intention is not guessed.

### The profile is a rendered response file

Each profile role renders a `manageprofiles` response file from the model and
hands it over with `-response`. One reviewable artefact per host instead of
fifteen arguments inside a shell line.

```
create                                          create
profileName=Dmgr_PREPROD_Extranet               profileName=AppSrv01
templatePath=.../profileTemplates/management    templatePath=.../profileTemplates/managed
serverType=DEPLOYMENT_MANAGER                   nodeName=<host>Node
cellName=Extranet_PREPROD                       federateLater=false
nodeName=PDmgrNode                              dmgrHost=<the dmgr>
startingPort=30000                              dmgrPort=<its real SOAP port>
enableAdminSecurity=true                        dmgrAdminUserName=...
```

The file is rendered on **every** run and removed afterwards. A response file
kept between runs is a second definition of the profile, and the one that
drifts is always the one somebody reads. `profile_keep_response` keeps it when
a creation failed and the exact input matters more than the tidiness; it is
mode 0600 and the task is `no_log`, because it carries the administrative
password while it exists.

Ports: an empty `profile_dmgr_ports` / `profile_node_ports` /
`profile_standalone_ports` means `-startingPort` from `was_base_port`. Fill one
in and a `-portsFile` is rendered instead, keyed exactly as `portdef.props`
names each endpoint - whatever keys the inventory declares are what is written.

### What the form does not ask for, deliberately

**The deployment manager's host and SOAP port.** The inventory already says
which host is the deployment manager; the deployment manager itself says which
port it listens on. Asking an operator to retype either creates two sources
that can disagree, and the disagreement surfaces as a node that will not
federate.

So `profile_dmgr` **reads** `properties/portdef.props` from the profile it just
created and publishes the real SOAP port, and `profile_nodeagent` federates
against that. Note that `was_dmgr_soap_port` in `40_runtime.yml` is derived as
`was_base_port + 5`, which is what the source estate happened to end up with -
`manageprofiles -startingPort` promises no such offset, the profile template
decides the allocation order. It is therefore an expectation that gets reported
when it disagrees, not a source of truth.

Before federating, the node checks that something is listening on that port
**from the node**, not from the controller. Federation against a deployment
manager that is not up fails inside `addNode` with an exception that reads like
a credential problem; it is refused here instead, with a message that names the
real cause and says where to read the real port.

**Node agent hosts, node names and ports** come from the inventory: the hosts
in the node agent group, `was_node_name` per host where the site standard
differs. An AWX survey is flat - it has no repeating group - so a list of nodes
cannot be expressed as survey questions. The survey carries only an optional
override that applies to every host in the run.

### Simulating is a check run, and that is all it is

**"Simulate the installation" means `--check`** — which AWX offers as
**Job type: Check** in the launch dialog, and which the pipeline passes
directly. There is no dry-run flag of this collection's own: a second code path
is a second thing to keep true, and it would be the one nobody launches.

The job templates shipped with `ask_job_type_on_launch` false, so Check was not
selectable and the only way to rehearse an install was to perform it.
[`ci/awx/apply-survey.sh`](ci/awx/apply-survey.sh) sets it, along with the
survey, so Run and Check are both reachable from the launch dialog.

What the profile roles do under check mode:

- the `command` tasks do not run, so `manageprofiles` is never called
- the hard refusals — the product is missing, the deployment manager is not
  listening, the profile did not land — stand down, because in a check run they
  are describing a future, not a state
- the read-only probes keep `check_mode: false`, so `-listProfiles` and the
  `stat`s still run and still report honestly
- each role prints **what it would hand to `manageprofiles`**, rendered on the
  controller with `lookup('template', ...)`, which writes nothing anywhere. The
  administrative password is masked out of the display; the file it would be
  written into is mode 0600 and the task is `no_log`

`sim:profiles` runs exactly that against the three simulation pods, where there
is no WAS and there is not meant to be, and asserts on the rendered response
file because that file is the contract between this collection and
`manageprofiles`: a `management` template with `serverType=DEPLOYMENT_MANAGER`
on the deployment manager, a `managed` template with `dmgrHost` and `dmgrPort`
on each node, no `default` template on a node, a standalone run reporting it
cannot cluster with both ND roles standing down, a topology of `whatever`
refused with a message naming the two accepted values, the password masked and
never in the log — and, last, that `/app/profiles` and `/app/data/profiles` are
empty on every simulated host afterwards.

## 18. The cluster and its application servers

**A cluster member is an application server.** The same object: one JVM, created
on a federated node and owned by the cell. `manageprofiles` never creates one —
the managed template produces a node agent and nothing else — so the member is
what turns a federated node into a node that runs an application, and it is a
separate job from the profile that carries it.

### Vertical, horizontal, or both — the member list decides

| Shape | What it is | How it is declared |
|---|---|---|
| **horizontal** | one member on each of several nodes | how many hosts the node agent group holds |
| **vertical** | several members on one node | `was_cluster_members_per_node` on those hosts |
| **both** | the product of the two, which is what an estate looks like | both of the above |

**There is no cluster-type variable anywhere**, and that is deliberate. A
cluster member is one JVM on one node; the shape is a consequence of the list
of members, never a switch that selects a mode. Two members per node over two
nodes is four JVMs, declared by one answer and one inventory group, and the
role reports the shape it built — `4 member(s) over 2 node(s) — vertical and
horizontal` — so an operator sees that the number they answered produced the
cluster they meant.

The names come from the same single pattern as every other WAS object, in
[`roles/model/vars/naming.yml`](ansible_collections/wasevo/websphere/roles/model/vars/naming.yml),
re-rendered once per index:
[`tasks/cluster_members.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/cluster_members.yml)
loops over the indices with `was_cluster_member_index` as the loop variable —
the variable the pattern already reads — so nothing composes a second,
vertical-aware form of the name.

| Input | Scope | Wins over |
|---|---|---|
| `was_cluster_members_per_node` | the whole run, from the survey | — |
| `was_cluster_member_names` | one node, a list, in the inventory | the count, including how many |
| `was_cluster_member_name` | one member, in the inventory or the survey | the pattern |

**One imposed name cannot name several JVMs.** Fill in the application server
name, answer two servers per node, and the run is refused — because appending
an index to a name somebody chose by hand invents a convention they did not
ask for. The refusal names both ways out: declare `was_cluster_member_names`
as a list, or leave the name unset and let the pattern number them. It is
decided by comparing the published name with what the pattern would produce,
so a name that happens to match the pattern — the lab writes its member name
out in full — raises no conflict.

### Two JVMs on one node cannot share a port

Each member is a JVM with its own `WC_defaulthost`, SOAP and ORB endpoints. On
a vertical cluster the second member would copy the first one's ports, and WAS
**saves that configuration without complaint**: the second server then fails to
start, possibly hours later, with an error about an address already in use, and
the configuration that produced it looks correct in the console.

So the module passes `genUniquePorts=true` and lets WAS allocate free ports.
Pin them instead with `was_cluster_member_ports` per host, keyed by member name
then by endpoint name as `serverindex.xml` spells it, when the IHS plugin or a
firewall rule needs a predictable port. Only the endpoints actually pinned are
read back and compared, so a member that pins nothing costs no extra reads —
and a pinned port that drifts is reported like any other difference.

`ci/assert-member-ports.py` asserts the property rather than describing it: it
reads the fake cell the simulation keeps and fails the build if any two servers
of one node hold the same port.

### One wsadmin session for the whole cluster

A wsadmin JVM start costs 30 to 60 seconds, so `was_cluster_member` takes the
**whole member list** in one call instead of one member per call. Eight members
built one at a time is eight starts and six minutes of JVM warm-up for a few
seconds of work.

- `-firstMember` is handled by the module, not by the caller. The WAS API
  requires it exactly once per cluster, on the call that fixes the server
  template every later member is copied from, and the handler knows from what
  it read whether the cluster is still empty.
- `weight` is read and reconciled, so a member can be drained to 0 — no new
  requests — without being deleted.
- Members the cell holds and the call does not name are **left alone**.
  Removal is `state: absent` on an explicit list, never a side effect of not
  naming something: a run limited to one node must not delete the members of
  every other node.
- Asking for members in a cell that has no such cluster is a **refusal with a
  sentence**, not a stack trace. A handler raises `ValueError` to refuse a
  request it understood; anything else keeps its traceback, because that is a
  defect rather than an answer.

### Each step is replayable on its own

**One role, one playbook, one job template.** Correcting one thing after a
change has to cost one wsadmin session, not the whole chain — otherwise the fix
is a rebuild and nobody does it.

| Playbook | Role | Replays |
|---|---|---|
| `traditional_cluster.yml` | `was_cluster` | the cluster object |
| `traditional_cluster_members.yml` | `traditional/server_member` | the application servers in it |
| `traditional_config.yml` | — | imports both, in order, and defines neither |

So each playbook **trusts no earlier workflow node**: it resolves the model
itself, stages the Jython driver itself, and checks its own preconditions.
A missing deployment manager profile is reported as "the profile job has to
run first", not as a wsadmin error three layers down — the same reason install
job 3 checks for `imcl` itself instead of trusting job 1.

`traditional_config.yml` carries the inline cluster task no longer. It imports
the two playbooks, which is what keeps one definition of each step: the legacy
`launch_*.sh` scripts each held their own copy of the same cell build, and the
copies disagreed.

**Why the member playbook has two plays.** A member name is built from the
**node** name, and the node is the only host that knows its own —
`was_node_name` can be a `group_vars` template that resolves only once the
model has published `was_env_upper` on that host. So the nodes publish their
member list first, gathering no facts and touching nothing, and the deployment
manager then reads `hostvars[<node>].was_cluster_members` and creates them,
which is where the single wsadmin session lives. A run limited to the
deployment manager alone cannot see those names, and the role says so rather
than building an empty cluster.

The host pattern of each playbook is overridable. It defaults to the
intersection of an environment group and the deployment manager group, so the
environment stays a launch input; the lab has no environment group on purpose —
the same VM is built as any environment — and passes
`-e config_dmgr_hosts=dmgr`, exactly as `lab_create_profiles.yml` already does
for the profile roles.

## 19. The resources of the cell

The roles are catalogued under **API families** - the list of the APIs an
application uses, which is how a team asks for a change ("our messaging", "our
persistence"). A family is a catalogue, never a merge: each role keeps its own
playbook and its own job template, replayable on its own, and a family
playbook imports its roles' playbooks in order.

| # | Family | Roles today | Family playbook | Next |
|---|---|---|---|---|
| 0 | Cell foundation | cluster, members (section 18) | `family_0_foundation.yml` | - |
| 1 | Web services and REST - JAX-RS, JAX-WS, JAX-RPC | policy sets | `family_1_web_services.yml` | attachments, with the application deployment |
| 2 | Persistence and data - JPA, JDBC | JDBC, JPA | `family_2_persistence.yml` | - |
| 3 | Enterprise components - EJB, CDI, JTA/JTS | transactions and peer recovery, EJB container and timers, CDI | `family_3_enterprise.yml` | - |
| 4 | Messaging and integration - JMS | SIBus, JMS on the bus and on IBM MQ | `family_4_messaging.yml` | - |
| 5 | Proprietary and extended APIs | SSL and signers, security and the user registry (all four types), J2C aliases, shared libraries, dynamic cache, logging and HPEL | `family_5_extended.yml` | - |
| 6 | JMX and management - PMI, MBeans | PMI | `family_6_management.yml` | - |
| 7 | MicroProfile | - | - | phase 2, the Liberty back-end |

Application deployment comes after all of them. Phase 1 has a role in every
family but MicroProfile, which is phase 2.

**Dependency order, not family order.** A datasource (family 2) presents a J2C
alias (family 5), so `traditional_config.yml` runs the steps in the order they
need each other, whatever their family - the step numbers below. A family
playbook run on its own relies on what the other families already built, and
each role refuses a missing prerequisite and names the job that produces it.

Each family of resources is its own role, its own playbook and its own job
template, in the order a cell needs them - and each is replayable on its own,
for the reason section 18 gives. They default to **cluster scope**, which
follows the vertical and horizontal members built just before; a resource
names another scope when it needs one.

| Step | Playbook | Resources | API family |
|---|---|---|---|
| 8 | `traditional_j2c.yml` | J2C authentication aliases | 5 |
| 9 | `traditional_jdbc.yml` | JDBC providers and datasources | 2 |
| 10 | `traditional_shared_libraries.yml` | shared libraries | 5 |
| 11 | `traditional_sibus.yml` | service integration buses | 4 |
| 12 | `traditional_jms.yml` | JMS resources, on the bus and on IBM MQ | 4 |
| 13 | `traditional_transactions.yml` | transaction service and peer recovery | 3 |
| 14 | `traditional_ejb_container.yml` | EJB container, cache and timers | 3 |
| 15 | `traditional_cdi.yml` | CDI | 3 |
| 16 | `traditional_jpa.yml` | JPA level and defaults | 2 |
| 17 | `traditional_ssl.yml` | SSL configurations and signers | 5 |
| 18 | `traditional_security.yml` | global security and the user registry | 5 |
| 19 | `traditional_policy_sets.yml` | web services policy sets | 1 |
| 20 | `traditional_dynamic_cache.yml` | dynamic cache and servlet caching | 5 |
| 21 | `traditional_logging.yml` | logging, trace and HPEL | 5 |
| 22 | `traditional_pmi.yml` | PMI | 6 |

### J2C authentication aliases

The credentials a datasource, a JMS connection factory or a bus member
presents. **Cell-wide, always**: an alias lives in the cell's security
configuration, so it takes no scope, and a datasource at cluster scope refers
to it by name. That is also why it comes first - a first build then needs no
second pass.

The declaration is the shared model's - layer 1 - and carries the **name** of a
variable, never a password:

```yaml
j2c_aliases:
  - name: as400ExtranetAlias
    user: wsextranet
    password_env: AS400_EXTRANET_PASSWORD
```

The role reads that variable from the controller's environment, which is
exactly where an AWX credential puts it. An alias with no password is refused
before wsadmin, by the name of the variable to fill, because an alias created
with an empty password authenticates nowhere and the failure would surface
hours later as a database refusing a connection.

**The password cannot be compared.** WAS stores it encoded and returns nothing
a plan could compare against, so the module does not pretend:

| `j2c_password_policy` | Does | Reports |
|---|---|---|
| `on_create` (default) | sets the password when the alias is created, then leaves it | changed only for what can be compared - the user and the description |
| `always` | writes the password on every run | changed on every run, because it might have |

**Rotating a database password is one replay of `traditional_j2c.yml` with
`-e j2c_password_policy=always`** - no cluster, no datasource, no application
touched. That is why aliases are a role of their own rather than a step of the
JDBC one.

The password never appears in what the module returns, so not in a diff and
not in a log; it travels only in the 0600 payload file the module removes. The
stub tests assert it: every driver answer about an alias, rotation included, is
searched for the password and must not contain it. And the fake cell refuses
to serve a stored password at all, because the real one returns it encoded - a
handler that read it back would pass in CI and break on a cell.

### JDBC providers and datasources

**One declaration, two back-ends.** A datasource is declared once, in the
shared model, and the Liberty back-end already renders it into `server.xml`.
The traditional back-end now renders the **same** declaration into wsadmin
arguments - that is layer 1 working, not two configurations kept in step.

```yaml
datasources:
  - name: as400Extranet
    jndi_name: jdbc/as400/extranet
    vendor: db2_i_toolbox
    driver_dir: /app/binaries/was90/jdbcprovider
    driver_jar: jt400.jar
    auth_alias: as400ExtranetAlias
    properties: { databaseName: EXTRANET, serverName: as400.example.internal }
    pool: { maxPoolSize: 30, minPoolSize: 5, connectionTimeout: 30s, maxIdleTime: 1800s }
```

**The vendor is an intent, translated by each back-end.** The model used to say
`vendor: db2` and the Liberty template wrote `<properties.db2>`, which is not a
Liberty element - for `jt400.jar` the element is `<properties.db2.i.toolbox>`.
[`roles/model/vars/jdbc_vendors.yml`](ansible_collections/wasevo/websphere/roles/model/vars/jdbc_vendors.yml)
now names the database and driver family once and gives each back-end its
rendering: the Liberty element, and the provider type and data store helper
`createJDBCProvider` and `createDatasource` need. The model refuses a vendor
neither back-end knows, before any render.

[`plugins/filter/traditional.py`](ansible_collections/wasevo/websphere/plugins/filter/traditional.py)
does the traditional rendering - Python rather than a Jinja block, because the
rules are worth testing on their own:

| Shared model | WAS traditional |
|---|---|
| `vendor: db2_i_toolbox` | provider type `DB2 UDB for iSeries (Toolbox)`, helper `DB2AS400DataStoreHelper` |
| `maxPoolSize`, `minPoolSize` | `maxConnections`, `minConnections` |
| `connectionTimeout: 30s`, `maxIdleTime: 1800s` | `connectionTimeout: 30`, `unusedTimeout: 1800` - seconds |
| `transactional: "false"` | custom property `nonTransactionalDataSource=true` |
| a pool key with no equivalent | **refused**, not dropped |

A setting that silently disappears on one back-end is a difference between the
two that nobody chose, so a key the table does not know is refused. Every
error of a declaration is reported at once.

**What WAS allows and should not**, refused before anything is written:

- a **provider type the cell does not offer**. The handler lists the cell's own
  JDBC provider templates first; a wrong entry in the vendor table fails on its
  first real run with the list of what the cell offers, rather than inside
  `createJDBCProvider` with an exception that names neither;
- a **datasource whose J2C alias does not exist**. WAS accepts it and the
  datasource fails at its first connection;
- a **datasource on a provider that does not exist** in that scope.

In a check run the last two are a future, not an absence: the step that
creates them ran in check mode too.

**Two WAS behaviours the handlers absorb.** The classpath is a list attribute,
and `AdminConfig.modify` **appends** to a list rather than replacing it - a new
driver jar written with a plain modify would leave the old one ahead of it on
the classpath, and the old driver would win. It is unset first, then written;
a stub test asserts the jar was replaced, not appended. And only the pool
settings and custom properties a declaration names are read back and compared:
a datasource carries dozens at their WAS defaults, and resetting the ones
nobody declared would overwrite tuning done in the console on purpose.

**Scope.** Cluster by default; a datasource declares `scope:` for another one -
`cell`, or `{type: server, node: ..., server: ...}`. The role groups by scope,
one wsadmin session per module per scope. Creating, providers go first;
removing, datasources go first, so nothing is left pointing at a driver that is
gone.

**Not yet verified on a real cell**: the provider types other than the IBM i
Toolbox one, and the data store helper class names. They are recorded in the
vendor table, which says so; the template check above is what turns a wrong
one into a sentence on the first lab run.

### Shared libraries

Declared in the shared model in one of two forms, and **both back-ends render
both**:

```yaml
shared_libraries:
  - name: appCommonLibrary        # a directory and a pattern
    dir: /app/binaries/shared
    includes: "*.jar"
  - name: reportingLibrary        # or an explicit list, in order
    jars: [/app/binaries/reporting/engine.jar, /app/binaries/reporting/fonts.jar]
```

**A pattern means the same thing on both sides.** Liberty reads `dir` +
`includes` as a fileset and rescans it at start. WAS traditional has **no
wildcard** in a library class path, so writing the directory alone would be a
different library on each back-end - a difference nobody chose. The role
expands the pattern on the deployment manager with the `find` module - a read,
so a check run does it too - and hands over the exact jars, sorted, because
`find` returns files in filesystem order and a class path that reshuffles
between runs would read as a change every time. A jar dropped into the
directory then shows up as a difference on the next run, which is how Liberty
behaves too, one restart later.

A pattern that matches nothing is **refused**: a library with an empty class
path provides nothing, and the applications using it would fail on their first
class load. The directory must hold the same jars on the deployment manager as
on every node that runs a member - a shared mount, or the deployment of the
application binaries, normally guarantees it.

The class path is a list attribute, so it is unset and rewritten, as for a JDBC
classpath. Associating a library with an application or a server class loader
is **not** done here: it belongs to the application deployment, which comes
last.

The simulation exercises both forms. `sim:configure` stages two jars **and a
README** in the pattern library's directory and asserts the library holds
exactly the two jars - the pattern honoured, not the directory taken whole.

### Service integration buses

The embedded messaging of WAS traditional, which JMS on the default messaging
provider runs on. **Traditional only**: Liberty has no bus, and moving there
means an external broker (section 10), so this declaration lives in the
traditional part of the model, not in the shared layer.

```yaml
sibuses:
  - name: OrdersBus
    members:                      # omitted: the run's cluster
      - { cluster: ClusterEXT01, store: file, policy: HA }
    destinations:
      - { name: OrdersQueue, max_failed_deliveries: 5, exception_destination: OrdersDeadLetters }
      - { name: OrdersDeadLetters }
      - { name: PricesTopic, type: topic_space, reliability: RELIABLE_NONPERSISTENT }
```

**One bus, one session.** `was_sibus` takes the bus, the members that host its
messaging engines and the destinations it carries, and reconciles them in one
wsadmin session, in the order they depend on each other. A bus that names no
member takes the run's cluster. The engine policy says how the cluster runs
its engines: `HA` is one engine that fails over between members, `SCALABILITY`
one engine per member - which is where the vertical members of section 18
start to matter for messaging.

**What a run never does: recreate an engine.** A member's message store and
its engine policy are fixed when the engine is created. Changing either means
removing the member and adding it back, which **discards every message the
engine holds**. So a declared store that differs from the live one is reported
as an Ansible warning and left alone - `changed` stays false, because the run
did not change it, and the warning says why. Losing messages has to be a
decision somebody takes, not a side effect of a replay. A stub test declares a
data store over a file-store engine and asserts the engine was not recreated.

The engine policy is applied when a cluster member is added and is **not**
read back: it lives in the core group's HA manager policies, not on the
member, and a plan that compared it would be comparing a guess.

Refused before anything is written: a bus with no member - no engine, so no
queue point and nothing to carry a message; an **exception destination** that
is not a destination of the bus - WAS accepts any string there, and failed
messages then have nowhere to go; and any value WAS constrains - a reliability
level, an engine policy - misspelt, with the accepted values listed. `state:
absent` deletes the bus, its members, their engines and their messages, and is
only ever explicit.

**Not yet verified on a real cell**: the `addSIBusMember` and
`createSIBDestination` arguments, and reading the store through the member's
engine. They follow the AdminTask reference; the lab run is what proves them.

### JMS resources

Connection factories, queues, topics and activation specifications - the four
kinds a message-driven bean needs - on the default messaging provider, whose
resources run on the bus of the previous step.

```yaml
jms:
  connection_factories: [{ name: OrdersCF, jndi_name: jms/ordersCF, bus: OrdersBus }]
  queues:               [{ name: OrdersQueue, jndi_name: jms/orders, queue: OrdersQueue, bus: OrdersBus }]
  topics:               [{ name: PricesTopic, jndi_name: jms/prices, topic_space: PricesTopic, topic_name: eur, bus: OrdersBus }]
  activation_specs:     [{ name: OrdersAS, jndi_name: jms/ordersAS, destination_jndi: jms/orders, bus: OrdersBus }]
```

**One handler, one table per provider.** The four kinds are the same idea on
the default messaging provider and on IBM MQ; what differs is the AdminTask
verbs and the attributes. `was_jms` carries a table per provider, so IBM MQ,
below, is a table and not a second handler. Resources are grouped by
scope and provider, one wsadmin session per group, read back through the
`show*` verbs - which flatten what a JMS resource keeps in property sets - and
compared on the fields the declaration names.

**What WAS accepts and should not**, refused before anything is written:

| Mistake | What WAS does with it |
|---|---|
| a JMS queue whose bus destination is missing, or is a topic space | saves it; the first send fails |
| a JMS topic on something that is not a topic space | saves it; the first publish fails |
| an activation spec listening on a JNDI no queue or topic carries, or of the wrong type | the message-driven bean deploys, starts, and never receives a message |
| a J2C alias that does not exist | the first connection fails |
| two resources on one JNDI name | the lookup returns whichever bound last |

An activation spec at cluster scope may listen on a queue declared at cell
scope - WAS resolves JNDI names through the scopes - so the role hands every
group the full list of declared queues and topics, and that configuration is
accepted; a stub test asserts it is. In a check run the bus and its
destinations may not exist yet, since the bus step ran in check mode too, and
the bus checks stand down. Creating, destinations go before what refers to
them; removing, what listens goes before what it listens on.

### JMS on IBM MQ

The same role, the same playbook, the same four kinds: a resource says
`provider: mq` and names a queue manager instead of a bus. What every factory
and activation spec of a run shares - the queue manager and the way to reach
it - is declared once, and a resource's own key wins:

```yaml
jms:
  mq_connection: { qmgr: QM1, transport: CLIENT, host: mq.example, port: 1414, channel: APP.SVRCONN }
  connection_factories: [{ name: PaymentsCF, jndi_name: jms/paymentsCF, provider: mq, type: QCF }]
  queues:               [{ name: PaymentsQueue, jndi_name: jms/payments, provider: mq, queue: PAYMENTS.IN }]
  topics:               [{ name: RatesTopic, jndi_name: jms/rates, provider: mq, topic_name: rates/eur }]
  activation_specs:     [{ name: PaymentsAS, jndi_name: jms/paymentsAS, provider: mq, destination_jndi: jms/payments }]
```

In the handler, IBM MQ is a second table, the `WMQAdminCommands` verbs
(`createWMQConnectionFactory`, `createWMQQueue`, `createWMQTopic`,
`createWMQActivationSpec`, and their list, show, modify and delete). An
activation spec's `max_concurrency` is the WMQ `maxPoolSize`, the server
session pool, whose default is 10 as on the bus.

**Only what a resource declares is compared.** WAS fills the MQ connection
attributes nobody set - a host, port 1414, a channel - and shows them back.
Comparing them against an undeclared field would report a change on every
replay; the fake cell fills them the way WAS does, and a stub test proves a
replay stays at `changed=false`.

**Refused before anything is written**, beyond what both providers refuse: a
`CLIENT` transport with neither a `host` nor a `connection_list` - WAS saves
it, and the first connection fails. In the model, an MQ resource that names a
bus, an MQ queue with no queue, an MQ topic with no topic string.

**Not proved yet**: the parameter names come from IBM's command reference;
that the `show*` verbs return them under the same keys is assumed, and the
first run against a real cell confirms it. The simulation declares an MQ
queue at cell scope and an activation spec at cluster scope listening on it;
no queue manager runs there, since configuring a resource connects nothing.

### Server settings: transactions, EJB container, CDI, JPA

Families 3 and 2 are not resources the cell holds once; they are settings
every application server carries - its transaction service, its EJB
container, its JVM, its JPA service. Four roles, one module,
`was_server_settings`, and one handler: each role translates an intent into
WAS attributes, the module applies them to every server of the target in one
wsadmin session.

```yaml
transactions:   { total_timeout: 2m, maximum_timeout: 5m, log_root: /shared/tranlog, peer_recovery: true }
ejb_container:  { cache_size: 3000, timers: { datasource_jndi: jdbc/ejbTimers, poll_interval: 5m } }
cdi:            { implicit_bean_archives: false }
jpa:            { spec_level: "2.1", provider: eclipselink, jta_datasource: jdbc/orders, non_jta_datasource: jdbc/reporting }
```

**The target is read from the cell.** A cluster target means the members the
cell holds now, not a list the run computed: a member added since the last
run is caught up by a replay, and none is left behind because the run did not
know it. A topology without a cluster names its server, `<role>_target:
{node, server}`.

**Restart, listed, never done.** These settings apply at server start. The
module returns `restart_required` - the servers whose configuration changed -
and warns about them; it restarts nothing. The four roles run last in
`traditional_config.yml`, so one restart takes them all.

**Attribute names are checked against the cell.** Before anything is
written, every declared attribute is looked up in `AdminConfig.attributes`
for its type, and an unknown name is refused with the valid ones. That is
also the safeguard for the names IBM's scripting reference does not show
(`enableHA` on the cluster, the two JPA default datasource attributes, taken
from `cluster.xml` and `server.xml`): the first run against a real cell
confirms them, or refuses before writing.

**What WAS accepts and should not**, refused before anything is written:

| Mistake | What WAS does with it |
|---|---|
| a transaction lifetime above `maximum_timeout` | caps it without a word |
| peer recovery with each recovery log under its own profile | accepts it; the surviving member cannot read the failed member's log, and recovery fails when it is needed |
| persistent EJB timers on several members, with no shared datasource or custom scheduler | each member keeps its own timer database; a timer created at startup fires once per member |
| a custom scheduler together with a timer datasource or table prefix | ignores the datasource |
| a JPA provider that does not implement the declared level | the server starts, every persistence unit fails |
| a JTA default on a datasource declared non-transactional, or the reverse | the persistence unit writes outside the transaction, or enlists what should stay out |
| a timer or JPA datasource the cell does not have | binds the name; the first use fails |

**Peer recovery** needs `log_root` on storage every member mounts; each
server's log goes to `<log_root>/<cell>/<node>/<server>` - the handler
replaces `{node}` and `{server}` for each server. Moving the log of a server
holding in-doubt transactions loses them: change `log_root` with the cluster
stopped or drained.

### Security: the four user registries

`security` configures one of the four registries WAS offers, makes it the
active one, and sets administrative, application and Java 2 security - one
role, one module, `was_security`, one wsadmin session.

```yaml
security:
  app_security: true
  registry:
    type: ldap                      # federated | ldap | localos | custom
    primary_admin_id: wasadm
    ldap:
      server_type: ACTIVE_DIRECTORY
      hosts: [ad1.example.com:636, ad2.example.com:636]
      base_dn: dc=example,dc=com
      bind_dn: cn=was-bind,ou=services,dc=example,dc=com
      bind_password_env: LDAP_BIND_PASSWORD
      ssl: true
```

| Type | What it is | What it needs |
|---|---|---|
| `federated` | the profile's own: a file repository, realm `defaultWIMFileBasedRealm` | the administrator, the realm |
| `ldap` | a standalone LDAP, hosts in failover order | server type, base DN, hosts; a bind DN with the variable carrying its password; TLS |
| `localos` | the operating system's users | a cell on one host |
| `custom` | a class of yours implementing `UserRegistry` | the class, on every process's class path; its properties |

**Written with IBM's verbs, read from the configuration.**
`configureAdmin<type>UserRegistry` configures the registry and, with
`-verifyRegistry`, makes WAS check that the administrator exists in it before
saving; `setAdminActiveSecuritySettings` activates it. What they wrote is read
back from `security.xml` with AdminConfig, which is what a replay compares.
The LDAP failover hosts and the custom registry's properties are made to
match with AdminConfig, since the verbs set one host and no list.

**The bind password** comes from a credential, by the name of the variable
that carries it, like a J2C alias password, and is never in a result:
`security_password_policy: on_create` writes it with the LDAP configuration,
`always` on every run - the rotation.

**What WAS accepts and should not**, refused before any session:

| Mistake | What WAS does with it |
|---|---|
| administrative security off | serves every administrative request unauthenticated |
| a registry made active without its administrator | locks every administrator out at the next start |
| an LDAP without TLS (unless `allow_plaintext: true`) | sends the bind password and every user's password in clear |
| a bind DN without the variable that carries its password | binds with an empty password, and fails later |
| settings of another registry type | keeps them, and ignores them |
| `localos` on a cell whose nodes run on several hosts (read from the cell) | checks each password against the operating system of whichever server answers |

**The whole cell restarts** for a security change to apply - the deployment
manager, the node agents, the servers. The module says so and restarts
nothing. After a registry change, `was_admin_user` must be a user of the new
registry: the role warns when it is not the registry's administrator.

### SSL configurations and signers

`ssl` manages SSL configurations at the cell or a node scope - key store,
trust store, protocol, cipher strength, client authentication - and the signer
certificates their trust stores need. `was_ssl_config`, one session.

```yaml
ssl:
  configs:
    - alias: CellDefaultSSLSettings
      scope: cell
      keystore: CellDefaultKeyStore
      truststore: CellDefaultTrustStore
      protocol: TLSv1.2
      security_level: HIGH
  signers:
    - alias: corp-ldap-ca
      host: ad1.example.com
      port: 636
```

**Before security**, in the chain: an LDAP over TLS is trusted through a
signer this role retrieves with `retrieveSignerFromPort`. A signer is
compared by alias; a peer whose issuer changed is a signer declared absent,
then present.

Refused before any session: a protocol that negotiates below TLS 1.2 -
`SSL_TLS`, `SSL_TLSv2`, `TLS`, `TLSv1`, `TLSv1.1`, any SSL; the accepted ones
are `TLSv1.2`, `TLSv1.3` and `TLSv1.2,TLSv1.3` - security level `LOW` or
`CUSTOM`, and deleting a default configuration of the profile. Refused by the
cell: a key store the scope does not have, since key stores come with the
profile or a certificate procedure this role does not stand in for.

When the cell's `dynamicallyUpdateSSLConfig` is off, the module lists the
cell to restart.

### Dynamic cache, logging and HPEL, PMI

Three more intents on `was_server_settings`, applied to every server of the
target read from the cell, with the servers to restart listed - the same
mechanism as the transactions, see the section above.

```yaml
dynamic_cache: { enabled: true, cache_size: 3000, disk_offload: true, disk_offload_root: /var/was/dynacache }
logging:       { mode: hpel, trace_spec: "*=info", repository_root: /var/was/logs, log_max_size: 500, log_max_age: 72h }
pmi:           { enabled: true, statistic_set: extended }
```

| Mistake | What WAS does with it |
|---|---|
| members sharing one disk offload directory | each overwrites the others' cache files - the role appends `<node>/<server>` to the root |
| a disk offload setting without `disk_offload: true` | keeps it, never uses it |
| a setting of the other logging mode | keeps it, never uses it |
| a trace specification that is not `<component>=<level>` | starts the server with it |
| PMI `custom` | needs a counter-by-counter specification this role does not carry |

`hpel` turns the HPEL service on and basic logging off in one change, as
IBM's procedure does; `*=all`, `*=finest`, `*=finer` and `*=fine` are
accepted with a warning. The HPEL trace specification attribute
(`startupTraceSpec`) is taken from `server.xml`; the handler checks it, like
every name, against `AdminConfig.attributes` before writing.

### Web services policy sets

`policy_sets` imports product default policy sets and copies them to adjust
the copies - `was_policy_set`, the PolicySetManagement verbs, one session.

```yaml
policy_sets:
  - { name: WSHTTPS default, from_default: WSHTTPS default }
  - name: Corporate HTTPS
    copy_of: WSHTTPS default
    policies: { WSAddressing: { enabled: true } }
```

**A default is never adjusted in place**: the next import of it would put the
product's version back. Policies on a `from_default` set are refused, and so
is a copy declared before its source. **Attachments belong to the application
deployment**, the last step: a set still attached to an application is
refused deletion, and the applications are named.

**Not yet confirmed on a real cell**: the format in which `getPolicySet` and
`getPolicyType` return their properties. The handler reads them as
`{key=value, ...}`, the way wsadmin prints a Java `Properties`.

## 20. AWX

AWX runs inside k3s on the Ubuntu host, deployed by the AWX Operator, pinned.
See [`ci/awx/README.md`](ci/awx/README.md).

**No `sudo` anywhere.** The account's `~/.kube/config` is readable, so the whole
install happens through the Kubernetes API; Ansible itself is installed per-user
with `pipx`.

Two things that bite on a first install, both fixed in the manifests:

- `gcr.io/kubebuilder/kube-rbac-proxy` was **retired by Google** — the
  repository is gone, not just the tag — so the operator pod sits in
  `ImagePullBackOff` out of the box. The kustomization redirects it to
  `quay.io/brancz/kube-rbac-proxy`, the component's upstream home.
- Applying the operator and the `AWX` custom resource in one kustomization is a
  race: the CR is rejected with `no matches for kind AWX` before the CRD is
  established. Hence the two-step apply.

`pipx install ansible` exposes only `ansible-community`; `--include-deps` is what
puts `ansible-playbook` on `PATH`.

The admin password is generated by the operator into a Secret. Nothing in this
repository carries it.

### A cell on k3s: deployment manager and two federated nodes

A dedicated AWX workflow, **WAS cell - deployment manager and two federated
nodes**, builds a cell from nothing on the k3s cluster - nothing is run by
hand, and it stops at the cluster: no JDBC, no JMS, no security change.

| Job | Playbook | What it does |
|---|---|---|
| 1 | `cell_machines.yml` | three KubeVirt virtual machines, through the Kubernetes API from the job pod |
| 2 | `cell_media.yml` | the Installation Manager and WAS media, copied from the install lab VM |
| 3 | `lab_install_im.yml` | Installation Manager on each machine |
| 4 | `lab_install_was.yml` | WAS on each machine |
| 5 | `lab_create_profiles.yml` | the deployment manager, started; then each node federated, one at a time |
| 6 | `traditional_cluster.yml` | the cluster |
| 7 | `traditional_cluster_members.yml` | one application server per node - a horizontal cluster of two |
| 8 | `traditional_start.yml` | the node agents and the members started; what runs is left alone |
| 9 | `cell_console.yml` | the console on the node address, checked through it |

The survey is the lab workflow's: the environment (`poc`), the channel
(`Extranet`), the topology (`nd`). They make the names - cell `Extranet_POC`,
cluster `ClusterEXT`, nodes `<machine>Node`, members
`ClusterEXT_<machine>Node_01`. The inventory, `inventories/cell`, names the
machines and nothing else.

**The console**: `http://lab.example.com:30000/ibm/console`. Port 30000 is a
NodePort onto the deployment manager's `WC_adminhost`; the login then
redirects to HTTPS on `WC_adminhost_secure`, published under its own number
(9043) on the same address by the cluster's service load balancer. Both ports
are read from the profile, not assumed.

**What made it possible**, and is reusable:

- `roles/platform/kubevirt_vms` - a machine per inventory host, its disk
  imported once and never again, a headless Service so every WAS port of the
  machine is reachable under a stable DNS name, the key of the AWX machine
  credential installed by cloud-init. The machine resolves its own name to
  its own interface - behind KubeVirt's masquerade the pod address is not
  local to it.
- `roles/platform/cell_media` - the WAS repository comes from IBM behind an
  IBMid; the install lab holds it, so the cell copies it from there over a
  transient HTTP server instead of asking for the IBMid again.
- `roles/traditional/server_start` - starts the deployment manager, node
  agents and members whose pid is not live, and nothing else. The deployment
  manager profile role now starts it: a node cannot federate otherwise, and
  nothing started it before.
- The profile roles take the product's default ports when the inventory
  gives no base port (`defaultPorts=true`): one profile per machine needs
  nothing else.

**Cluster access** is a ServiceAccount, `awx/awx-cell-platform`
(`ci/k3s/30-awx-cell-platform.yml`): create, read and patch on namespaces,
virtual machines, disks, Secrets and Services - no delete. AWX holds its token
as a Kubernetes credential. **The WAS administrator** is `wasadmin`, its
password generated once into the Secret `awx/was-cell-admin`, never in the
repository:

```sh
kubectl -n awx get secret was-cell-admin -o jsonpath='{.data.password}' | base64 -d
```

Everything in AWX is declared by `ci/awx/apply-cell-workflow.sh`, run from
the node.

### What AWX holds is declared, not clicked

[`ci/awx/apply-templates.sh`](ci/awx/apply-templates.sh) creates the job
templates that build a cell and chains them into the workflow in order; it is
re-runnable, finding every object by name and patching it. A job template is
configuration — which playbook, which inventory, which credential, whether
`Job type` is selectable — and clicking it means nobody can say what AWX is
supposed to hold. That is how three templates came to exist and the three that
build a cell did not.

It also declares the credential type for the WAS administrator, so
`was_admin_user` and `was_admin_password` reach a playbook as injected extra
vars — encrypted at rest, masked in the output — rather than sitting in a
template's `extra_vars` in plain text. It creates no credential: a password does
not come from a repository.

**AWX validates `playbook` against the project's last successful update**, not
against the repository, so the script updates the project and waits before
naming a playbook. A playbook pushed since that update is otherwise refused
with `Playbook not found for project.`, which reads like a path typo and is not
one.

### Resolved: AWX runs jobs on this Kubernetes, at 24.6.1

> **There is nothing to upgrade to, and nothing needed upgrading.** On
> 31 October 2026, inventory update 49 and ad hoc command 52 (`ping` on the
> three lab hosts) both succeeded on AWX 24.6.1, receptor 1.4.8, Kubernetes
> v1.37.0+k3s1.
>
> An earlier note here blamed receptor's **SPDY** attach and called for an AWX
> upgrade. Both halves were wrong, and were checked:
>
> - this cluster still serves SPDY: `kubectl exec` and `kubectl attach -i` with
>   `KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false` both work, the attach carrying
>   stdin into the pod;
> - no upgrade exists: awx-operator 2.19.1 (AWX 24.6.1) is still the last
>   release, and every receptor up to 1.6.9 and its `devel` branch still
>   attach through `NewSPDYExecutor`;
> - the job role already grants `pods/attach: create`, which WebSocket attach
>   requires.
>
> The October failures (`EOF for pod awx/automation-job-33-...`, then AWX's
> `Failed to JSON parse a line from worker stream ... b''`) were not
> reproduced, and their cause is not known. If they return, read the
> `awx-ee` container of the task pod
> (`kubectl -n awx logs deploy/awx-task -c awx-ee`) before suspecting the
> protocol. AWX stays pinned.

## 21. Sources

- [Supported Java SE versions — WebSphere Liberty (MoRE)](https://www.ibm.com/docs/en/SSNGA9K/ae/lj_java_se.html)
- [Java SE 8 in WebSphere Application Server traditional V9](https://www.ibm.com/docs/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/covr_javase8.html)
- [What is new in WebSphere Application Server traditional](https://www.ibm.com/docs/en/SSEQTP_9.0.5/was/ae/welc_newinrelease.html)
- [IBM Java SDKs for WebSphere Liberty](https://www.ibm.com/support/pages/ibm-java-sdks-websphere-liberty)
- [WebSphere Liberty images on IBM Container Registry](https://github.com/WASdev/ci.docker/blob/main/docs/icr-images.md)
- [createWMQConnectionFactory command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmscf_create.html)
- [createWMQQueue command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmswmqq_create.html)
- [createWMQActivationSpec command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmsas_create.html)
- [Configuring the timer service using scripting](https://ibm.com/support/knowledgecenter/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/txml_ejbTimer_config.html)
- [Configuring the runtime transaction service using scripting](https://www.ibm.com/support/knowledgecenter/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/txml_transaction.html)
- [Identifying and modifying the JPA specification level](https://www.ibm.com/docs/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/tejb_idmod_jpaspec.html)
- [Custom properties for improving application startup](https://www.ibm.com/support/pages/custom-properties-improving-application-startup-websphere-application-server)
- [SecurityConfigurationCommands command group for the AdminTask object](https://www.ibm.com/docs/en/SSEQTP_8.5.5/com.ibm.websphere.base.doc/ae/rxml_7securityconfig.html)
- [SSLConfigCommands command group for the AdminTask object (9.0.5)](https://www.ibm.com/support/knowledgecenter/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/rxml_atsslconfig.html)
- [SignerCertificateCommands command group (9.0.5)](https://www.ibm.com/docs/en/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/rxml_atsignercert.html)
- [Configuring HPEL with wsadmin scripting](https://www.ibm.com/docs/en/SSAW57_8.5.5/com.ibm.websphere.nd.multiplatform.doc/ae/ttrb_confHPELwsadmin.html)
- [Changing from basic mode to HPEL logging and tracing (9.0.5)](https://www.ibm.com/docs/en/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/ttrb_compToHPEL.html)
- [Importing and exporting policy sets using wsadmin scripting](https://www.setgetweb.com/p/WAS9/ae/was6091.html)
- [Managing policy set attachments using wsadmin scripting](https://setgetweb.com/p/WAS9/ae/was6092.html)

Source-repository findings come from direct inspection of the seven archives in `github.com/CGA71/WAS`.

---

<a name="français"></a>

# Français

## 1. De quoi il s'agit

Une collection Ansible unique qui administre l'ensemble du parc WebSphere — WAS ND traditionnel aujourd'hui, Liberty sur OpenShift demain — depuis une source de vérité unique.

Elle remplace un patrimoine existant (environ 800 fichiers, 86 scripts Jython, 34 fichiers de tâches `wsadmin_*`, 4 scripts shell de lancement) qui ne s'exécute plus sur un `ansible-core` récent et dont l'idempotence est simulée par des fichiers témoins.

### Décisions d'architecture

| Sujet | Décision | Raison |
|---|---|---|
| Forme du livrable | Une **collection Ansible**, pas un dossier de rôles | Seul format qu'un Execution Environment sait charger ; le FQCN supprime le bricolage de liens symboliques |
| Plan traditionnel | Des **modules** pilotant un driver Jython unique | wsadmin est impératif : l'idempotence, le `--check` et le `--diff` doivent être construits |
| Plan Liberty / OpenShift | **Aucun module** — `kubernetes.core` et la CRD de l'opérateur Liberty | Kubernetes réconcilie déjà. Écrire des modules Liberty serait réécrire `kubernetes.core` en moins bien |
| Source de vérité | **Un modèle YAML partagé**, deux back-ends de rendu | La migration devient un changement de back-end au lieu d'une réécriture d'inventaire |
| Inventaire | **Tout YAML** | Le plan configuration manipule des structures imbriquées que l'INI ne sait pas exprimer |
| Convergence OpenShift | **Ansible applique** pour démarrer ; frontière GitOps préservée | `config_render` et `deploy` restent deux rôles distincts : adopter Argo CD plus tard ne coûte rien |

### Le principe directeur

Le plan traditionnel et le plan Liberty ne partagent presque aucune mécanique d'automatisation. Ils partagent une *intention de configuration*. Cette architecture isole cette intention dans une couche unique et accepte deux back-ends franchement dissemblables en dessous. Toute tentative de faire ressembler l'un à l'autre échoue.

## 2. Architecture

```
COUCHE 1 — SOURCE DE VERITE
  Modele YAML agnostique produit : datasources, fournisseurs JDBC, alias J2C,
  proprietes JVM (en intentions, pas en options), applications, keystores, securite.
  Environ 40 % du perimetre, reellement commun. Valide par schema avant tout rendu.
        |
        +-----------------------+-----------------------+
        v                       v                       v
COUCHE 2a                 COUCHE 2b                COUCHE 2c
TRADITIONNEL              LIBERTY SUR OPENSHIFT    LIBERTY ADMINISTRE (MoRE)
modules -> driver         modele -> server.xml     ND 9.0.5.23+ pilote
Jython -> wsadmin         -> ConfigMap -> CRD      Liberty depuis la cellule,
un lancement de JVM       applique par             console + wsadmin + JMX
par lot                   kubernetes.core          (le pont de migration)
        |                       |                       |
        +-----------------------+-----------------------+
        v
COUCHE 3 — ORCHESTRATION
  Ansible Automation Platform : Workflow Templates, Surveys, Approval Nodes,
  Credentials types, promotion d'un environnement au suivant, tests de fumee.
```

### Pourquoi le plan Liberty n'a aucun module

Les modules `was_*` existent parce que wsadmin est impératif et qu'il faut y fabriquer l'idempotence. Sur OpenShift, `kubernetes.core.k8s` fait déjà le lire-puis-écrire, avec un `changed` réel et un `--diff` réel via server-side apply.

### La limite, assumée d'emblée

Ne pas unifier plus que ce qui l'est. Le recouvrement est réel sur les datasources, les propriétés JVM, les bindings applicatifs et la sécurité. Il est **nul** sur la cellule, les profils, les nodeagents, les templates de serveur, le SIBus et IHS d'un côté ; sur les `replicas`, les sondes, les quotas, les Routes et le `featureManager` de l'autre. Le modèle a donc une section commune et deux sections spécifiques. C'est sur la fausse symétrie que ces projets meurent.

## 3. Organisation du dépôt

```
ansible_collections/wasevo/websphere/
  plugins/
    module_utils/wsadmin.py      lancement, parsing JSON, no_log
    modules/                     plan TRADITIONNEL uniquement
    jython/
      driver.py                  point d'entree unique wsadmin
      handlers/                  read() / write() par type de ressource
  roles/
    model/                       validation de schema + table de traduction JVM
    traditional/                 prereqs_os (RHEL + AIX), installation_manager,
                                 was_install, was_fixpack, was_sdk,
                                 profile_dmgr, profile_nodeagent, server_member,
                                 ihs, config, audit
    liberty/
      config_render/             modele -> server.xml — AUCUN acces cluster
      image_build/               Dockerfile ou S2I, tag, push registre
      deploy/                    CRD + ConfigMap + Secret via kubernetes.core
      verify/                    k8s_info + test de fumee
  playbooks/
inventories/                     un inventaire tout YAML ; l environnement est une entree
model/                           le modele declaratif partage
docs/                            architecture et notes par phase
ci/
  k3s/                           pods de simulation, la VM de lab, RBAC,
                                 make-lab-vm.sh, lab-mirror-was.sh
  awx/                           l'operateur AWX et ses kustomizations
```

**Ne jamais fusionner `config_render` et `deploy`.** `config_render` ne touche pas le cluster : il s'exécute hors ligne, est testable sans OpenShift, et c'est la frontière GitOps. Si Argo CD est adopté, `config_render` produit et commite, `deploy` est débranché, et rien d'autre ne change.

## 4. Matrice produit × JDK

| | IBM SDK Java 8 | Semeru 17 | Semeru 21 | Semeru 25 |
|---|---|---|---|---|
| **WAS ND 9.0 traditionnel** | seule option supportée | non | non | non |
| **Liberty administré (MoRE)** | diagnostic seulement | oui (fin 10/2027) | ND >= 9.0.5.25 | ND >= 9.0.5.29 |
| **Liberty sur OpenShift** | écarté (UBI Standard) | oui | **cible** | oui |

WAS ND 9.0 traditionnel est verrouillé sur IBM SDK Java Technology Edition 8. Java 17 et 21 ne sont pas disponibles sur le moteur traditionnel ; ils ne sont atteignables que par Liberty. **La dimension JDK n'est donc pas orthogonale à la dimension produit** — `roles/model` le fait respecter au rendu, pas sur la cellule.

### Deux conséquences pour la trajectoire

1. **Le saut de JDK ne peut pas avoir lieu avant Liberty.** Le moteur traditionnel ne dépasse pas Java 8.
2. **Il ne doit pas non plus avoir lieu après la conteneurisation.** Cela obligerait à construire une image Liberty sur IBM Java 8, donc sur UBI Standard — la variante qu'IBM retire après Liberty 26.0.0.12. La phase 2 est le seul endroit où ce changement a sa place.

### « OpenJDK 21 » signifie ici OpenJ9

Les images officielles WebSphere Liberty sur `icr.io/appcafe` embarquent **IBM Semeru Runtime, donc OpenJ9**, pour Java 8, 11, 17, 21 et 25. Il n'y a pas de variante HotSpot/Temurin dans le jeu officiel. C'est une bonne nouvelle : le tuning JVM existant est massivement spécifique à J9 et survit pour l'essentiel. Sur Temurin, `-Xgcpolicy`, `-Xmns`/`-Xmnx`, `-Xshareclasses`, `-Xdisableexplicitgc` et `-Xverbosegclog` ne survivent pas : la JVM refuse de démarrer sur un `-X` inconnu, ou ignore silencieusement la journalisation GC — ce qui est pire. **Rester sur les images IBM, ou refaire intégralement le tuning.**

## 5. Phase 1 — WAS traditionnel + IBM JDK 8

> **État cible :** le parc actuel, rendu idempotent, auditable et rejouable.
> **Cette phase se justifie seule, même si aucune application ne migre jamais.**

### Vague 0 — Socle (rien ne change en production)

**Actions**

1. Créer le squelette de la collection, `galaxy.yml`, `meta/runtime.yml`.
2. Écrire `module_utils/wsadmin.py` : lancement, fichier de payload 0600, parsing JSON, `no_log`.
3. Écrire `plugins/jython/driver.py` : point d'entrée wsadmin unique, routage vers les handlers, retour JSON sur stdout.
4. Écrire le module pilote `was_cluster` et son `handlers/cluster.py` (`read()` / `write()`).
5. Écrire `roles/model` : validation de schéma et table de traduction des options JVM.
6. Écrire `roles/liberty/config_render` avec les templates `server.xml`, `jvm.options` et `server.env`.
7. Construire les deux Execution Environments : `ee-was-traditional` et `ee-liberty-ocp`.
8. Créer le projet AAP, deux inventaires, les types de Credentials, le premier Workflow Template.
9. Reconstruire le premier environnement hors production avec le nouvel outillage, à iso-fonctionnalité.
10. Rendre le datasource pilote, déclaré une seule fois, dans les trois couples de la trajectoire.

**Critères d'entrée** — dépôt GitLab, AAP joignable, une cellule hors production disponible pour reconstruction.

**Critères de sortie** — cette cellule reconstruite de bout en bout depuis AAP ; `--check` et `--diff` démontrés sur un changement réel ; les trois rendus du datasource pilote concordent.

**Retour arrière** — les anciens `launch_*.sh` restent exécutables en parallèle.

### Vague 1 — Industrialisation du plan traditionnel

**Actions**

1. Porter les 34 types de ressources `wsadmin_*` en modules, priorisés par **fréquence d'usage réelle**, pas par ordre alphabétique.
2. Implémenter les ~29 suppressions manquantes. `state: absent` est annoncé sur 34 types et implémenté sur 5 ; `clusterDestroy` est en commentaire.
3. Créer `was_application` pour le déploiement, la mise à jour et la suppression de war/ear. Cela n'existe pas aujourd'hui : il n'y a pas un seul appel `AdminApp.install` dans le dépôt source.
4. Retirer le mot de passe de la ligne de commande partout — argument de module avec `no_log: true`, ou `soap.client.props`.
5. Ajouter le support AIX à `prereqs_os`. Il y a actuellement zéro référence à AIX dans le dépôt source.
6. Retirer RedHat 5 et 6 des prérequis OS.
7. Séparer les variables : le spécifique environnement reste dans l'inventaire, le spécifique produit devient les `defaults/` des rôles.
8. Écrire `roles/traditional/audit`, exécutable en `--check --diff`, produisant l'écart entre état déclaré et état réel.
9. Convertir les 4 `launch_*.sh` en Workflow Templates avec Surveys et Approval Nodes.

**Critères d'entrée** — critères de sortie de la vague 0 atteints.

**Critères de sortie** — toute cellule rejouable sans effet de bord ; écart détecté et montrable ; déploiement applicatif automatisé ; aucun secret en ligne de commande ni dans un log.

**Retour arrière** — par module ; les anciens fichiers de tâches restent dans l'historique git.

## 6. Phase 2 — Liberty + OpenJDK 21 et plus

> **État cible :** Liberty et Semeru 21 sur les machines existantes, toujours administrés par wsadmin via MoRE.
> Le runtime et le JDK changent ensemble ici, parce que la section 4 ne leur laisse nulle part ailleurs à aller.

### Vague 2 — Évaluation applicative

**Actions**

1. Passer chaque application au Migration Toolkit d'IBM (analyse de binaires).
2. Classer selon la grille de la section 8.
3. **Arbitrer la question du SIBus.** Six types de ressources SIBus dans le dépôt source signalent un usage réel de la messagerie embarquée. Liberty n'a pas de moteur de messagerie intégré : un broker externe est nécessaire (MQ, Artemis, Kafka). C'est une décision d'architecture applicative, pas d'infrastructure.
4. Confirmer le point de vérification ouvert de la section 9 avant tout engagement de planning.
5. Produire le backlog ordonné, avec charge estimée et dépendances bloquantes nommées.

**Critères d'entrée** — phase 1 terminée ; équipes de développement disponibles, pas seulement l'exploitation.

**Critères de sortie** — chaque application rangée dans l'une des quatre catégories, avec charge et bloquants nommés.

### Vague 3 — Liberty et Semeru 21 sur place

**Actions**

1. Ne retenir que deux ou trois applications de **catégorie A**.
2. Rendre `server.xml`, `jvm.options` et `server.env` depuis le modèle partagé via `config_render`.
3. Appliquer la table de traduction des options JVM : politique GC, nursery, cache de classes partagé, dumps, journal GC.
4. Basculer la supervision sur `monitor-1.0` / MicroProfile Metrics. **PMI n'existe pas sur Liberty** — cela doit être prêt maintenant, pas en phase 3.
5. Déployer Liberty sur les machines existantes, sous `liberty_more` ou en autonome.
6. Basculer et revenir par le plugin IHS.
7. Observer, puis recommencer avec les applications suivantes.

**Palier de diagnostic** — si une application ne démarre pas, rejouer le **même** `server.xml` sous IBM Java 8 pour séparer un problème de runtime d'un problème de JDK. **Sur machine uniquement, jamais en image.** Abandonner le palier dès le diagnostic posé.

**Critères d'entrée** — application classée A ; remplacement de la supervision prêt.

**Critères de sortie** — application fonctionnelle sur Liberty + Semeru 21 ; tuning JVM traduit et vérifié.

**Retour arrière** — la cellule WAS ND d'origine est intacte ; retour par le plugin IHS.

## 7. Phase 3 — OpenShift + Liberty + OpenJDK 21 et plus

> **État cible :** la même configuration Liberty et le même JDK, désormais en image immuable pilotée par la CRD de l'opérateur.

### Vague 4 — Conteneurisation (le packaging change, la configuration non)

**Actions**

1. Construire l'image sur `kernel-java21-openj9-ubi-minimal`, ou `ubi-micro` si la version de Liberty le permet (26.0.0.9+). Préférer `kernel` et déclarer explicitement les features dans `server.xml`.
2. Remplacer le `-Xmx` fixe par `-XX:MaxRAMPercentage`. **Un `-Xmx` fixe face à une `memory limit` de pod, c'est l'OOMKilled assuré.**
3. Pointer les répertoires de dumps vers un volume persistant.
4. Pointer le cache de classes partagé vers un volume, sinon il est reconstruit à chaque démarrage.
5. Rediriger le journal GC hors du système de fichiers du conteneur.
6. Exécuter l'image en local ou sur un socle de conteneurs d'essai.

**Critères d'entrée** — critères de sortie de la vague 3 atteints pour l'application concernée.

**Critères de sortie** — image démarrant avec la configuration issue du modèle, sans `-Xmx` fixe, dumps persistés, journal GC accessible.

**Preuve** — le même modèle et le même JDK produisent la configuration de la vague 3 sur machine et celle de la vague 4 en image. Si les deux divergent, le défaut est dans le rendu, pas dans l'application.

### Vague 5 — OpenShift (la plateforme change, rien d'autre)

**Actions**

1. Déployer par la ressource `WebSphereLibertyApplication` (`OpenLibertyApplication` pour Open Liberty). Une seule ressource remplace Deployment, Service, Route, ServiceAccount et sondes.
2. Rendre ConfigMap et Secret ; sourcer les secrets depuis un Credential AAP ou l'External Secrets Operator — **jamais depuis un fichier versionné**.
3. Configurer la Route, les sondes liveness et readiness, les requests et limits.
4. Mettre en place les dumps et traces via `WebSphereLibertyDump` et `WebSphereLibertyTrace`.
5. Brancher Prometheus sur les métriques exposées en vague 3.
6. Construire le workflow de promotion : `render -> build -> push -> [Approval] -> premier environnement -> smoke -> [Approval] -> suivant -> ... -> production`.

**Critères d'entrée** — critères de sortie de la vague 4 atteints.

**Critères de sortie** — application en production sur OpenShift ; retour arrière par rollout.

**Remarque** — le runtime, le JDK et l'image sont déjà figés et éprouvés depuis les vagues 3 et 4. C'est tout l'intérêt de cet ordre.

### Vague 6 — Décommissionnement

**Actions**

1. Supprimer les serveurs, clusters et nœuds migrés. **Ce n'est possible que grâce aux ~29 suppressions créées en vague 1.**
2. Réduire le périmètre IHS.
3. Libérer les licences.
4. Conserver le parc traditionnel résiduel sous la même collection.

**Critères de sortie** — périmètre traditionnel réduit à ce qui ne peut pas migrer, toujours automatisé par un seul outil.

## 8. Classification applicative

| Catégorie | Critères | Trajectoire |
|---|---|---|
| **A — Reprise directe** | Java EE 7 ou moins, pas de SIBus, pas d'API WebSphere propriétaire, pas de JAX-RPC, pas d'EJB distant, état en session seulement, aucune dépendance au système de fichiers local | Vagues 3 → 4 → 5 sans retouche de code. **Commencer ici** |
| **B — Reprise avec ajustements** | Bibliothèques partagées, classloaders isolés, WorkManagers, startup beans, transactions XA, WS-Security | Vague 3 après reconfiguration. Charge modérée, concentrée sur la configuration |
| **C — Dépendance bloquante** | **SIBus** et messagerie embarquée, policy sets WS-Security complexes, PMI exploitée par la supervision, dépendance à la console d'administration | Décision d'architecture préalable. Ne pas engager avant arbitrage du broker |
| **D — `javax` → `jakarta`** | Cible Jakarta EE 10 ou plus, changement d'espace de noms | Réécriture partielle. Projet applicatif, pas d'infrastructure |

**Règle d'ordonnancement** — faire traverser deux ou trois applications de catégorie A jusqu'en vague 5 incluse avant d'engager quoi que ce soit en B. Le but n'est pas d'aller vite : c'est de faire passer un cas réel par toute la chaîne (modèle, rendu, image, CRD, supervision, promotion). Les défauts de la chaîne se révèlent sur la première application ; autant qu'elle soit simple.

## 9. Point de vérification ouvert

> **`javaee-8.0` sur Semeru 21.**
>
> C'est l'hypothèse qui tient la phase 2 pour les applications de catégorie A — celles qu'on a précisément choisies pour ne pas les réécrire. Les features Liberty portent des exigences de niveau Java. Si ce couple n'est pas supporté sur la version de Liberty retenue, la migration `javax` → `jakarta` devient obligatoire pour tout le monde, et l'ampleur du programme change radicalement.
>
> **À confirmer avant tout engagement de planning.** Ce n'est pas confirmé dans les documents IBM consultés à ce jour.

## 10. Trous fonctionnels — ce qui doit être remplacé, pas migré

| Fonction WAS ND | Présence dépôt source | Sur Liberty | Action |
|---|---|---|---|
| **SIBus / messagerie embarquée** | 6 types `wsadmin_sibus*` + `pbk_dmgr_creation_sibus.yml` | aucun équivalent | Broker externe. Décision d'architecture applicative |
| **Policy sets WS-Security** | `createWSSecurityPolicy.py`, 6 XML de liaisons | modèle différent | Feature `wsSecurity-1.1`, configuration réécrite |
| **Supervision PMI** | `pmiConfig`, `pmiModuleConfig`, `-XrunpmiJvmtiProfiler` | n'existe pas | `monitor-1.0`, MicroProfile Metrics, Prometheus |
| **Collecte javacore / heapdump** | `SearchFile.ksh` + cron 15 min, FS dédié `/app/dump/was` | à reconstruire | PVC, ou CR `WebSphereLibertyDump` |
| **Réplication de session (DRS)** | implicite dans les clusters | modèle différent | `sessionCache` (JCache : Infinispan, Hazelcast) ou routage collant |
| **Virtual hosts** | `wsadmin_virtualhost`, `wsadmin_virtualhostAlias` | concept absent | Routes OpenShift. La notion disparaît |
| **IHS, plugin, propagation** | rôle IHS complet, `propagatePlugin.py` | sans objet | Route / Ingress. Le rôle IHS reste utile au parc résiduel |
| **Bibliothèques partagées** | `wsadmin_sharedLibrary` | supporté | `<library>` et `<classloader>` dans `server.xml` |
| **Datasources, JDBC, J2C** | 7 types de ressources, 5 drivers embarqués | supporté | Cœur de la couche 1. Se rend dans les deux back-ends |

## 11. Exécution

```bash
COL=ansible_collections/wasevo/websphere/playbooks

# installer les dependances
ansible-galaxy collection install -r collections/requirements.yml

# rendre le datasource pilote dans les trois couples de la trajectoire. Sans
# inventaire - le play tourne sur localhost - mais l'environnement reste une
# entree : le modele nomme chaque objet qu'il rend
ansible-playbook $COL/pilot_render_matrix.yml -e was_environment=PILOT

# valider un environnement - l'environnement est une entree de lancement et
# pas un repertoire, donc il se passe meme pour une validation qui ne touche
# a rien
ansible-playbook -i inventories/was $COL/model_validate.yml -e was_environment=RA

# plan traditionnel, a blanc d'abord - toujours
ansible-playbook -i inventories/was $COL/traditional_config.yml -e was_environment=<code> --check --diff

# ou une etape a la fois : chacune est rejouable seule, soit une session
# wsadmin au lieu de toute la chaine. Voir la section 18.
ansible-playbook -i inventories/was $COL/traditional_cluster.yml -e was_environment=<code> --check --diff
ansible-playbook -i inventories/was $COL/traditional_cluster_members.yml -e was_environment=<code> -e was_cluster_members_per_node=2

# Dans AWX aucune de ces options ne se tape : le formulaire demande
# l'environnement, le canal, le nombre de serveurs d'application par noeud et
# l'acquittement production.
```

### Execution Environments

| EE | Contenu | Cible |
|---|---|---|
| `ee-was-traditional` | `ansible-core` + cette collection. **Pas de Java, pas de Jython** — le driver part sur la cible et s'exécute dans le wsadmin de la cible | WAS ND, AIX et RHEL |
| `ee-liberty-ocp` | `ansible-core` + `kubernetes.core` + `redhat.openshift` + la bibliothèque Python `kubernetes` | Liberty sur OpenShift |

### Notes AAP

- **L'inventaire du plan Liberty est `localhost`.** On ne se connecte à rien : le job tourne dans l'EE et parle à l'API OpenShift.
- **Les nœuds d'un workflow ne partagent pas les facts.** Une valeur qui traverse deux nœuds — le tag d'image produit par le build — passe par `set_stats`.
- Régler les timeouts des Job Templates large : un lot wsadmin dure des minutes.
- `serial` reste dans le playbook pour les redémarrages en cascade. Ce n'est pas un découpage de workflow.

## 12. Sécurité

Ce dépôt est **public sur le GitLab interne pour l'instant**, délibérément, afin d'éviter les frictions de token pendant l'amorçage. Il sera restreint ultérieurement. En attendant :

- **Aucun secret n'est commité.** Aucun keystore, aucun `.p12`, aucun `keyfile.kdb`/`.sth`, aucun mot de passe dans un inventaire.
- Les secrets passent par les Credentials AAP, Ansible Vault, ou des fichiers 0600 — jamais en argument de ligne de commande.
- Les expositions du dépôt source ne sont **pas** reprises : 58 manifests `Secret` Kubernetes avec leur bloc `data:` renseigné (dont `PRD/`), 14 keystores `.p12`, et `was_admin_password: "wsadmin"` / `was_keystore_password: "password"` dans les `group_vars`.

> **Action requise sur le dépôt source**, indépendamment de ce projet : le base64 d'un `Secret` Kubernetes n'est pas du chiffrement. Faire tourner les identifiants de bases concernés, puis purger l'historique git — supprimer le fichier ne suffit pas, il reste dans les commits.

## 13. Risques

| Point | Nature | Traitement |
|---|---|---|
| **`javaee-8.0` sur Semeru 21** | risque de périmètre — à vérifier d'abord | Voir section 9. À confirmer avant tout engagement de planning |
| **SIBus** | risque structurel | Arbitrage du broker avant la vague 2. Conditionne quelles applications migrent et dans quel ordre |
| **Volume de portage** | risque de charge | 34 types de ressources. Mécanique et parallélisable, mais long. Prioriser par fréquence d'usage réelle |
| **Couche 1** | risque d'architecture | Validée ou invalidée en vague 0 sur un seul objet rendu trois fois. Une journée, pas trente modules plus tard |
| **UBI Standard** | échéance fournisseur | Arrêt après Liberty 26.0.0.12. C'est pourquoi *Liberty + IBM JDK 8* est écarté des cibles |
| **Java SE 17** | échéance fournisseur | Fin de support octobre 2027 côté Liberty administré. La trajectoire vise 21 directement et ne fait pas étape en 17 |
| **Supervision** | trou fonctionnel | PMI n'existe pas sur Liberty. La bascule doit être prête dès la **vague 3**, pas en phase 3 |
| **Compétences** | risque humain | Deux cultures qui cohabiteront longtemps. La couche 1 est aussi ce qui permet aux deux équipes de parler du même objet |

## 14. La forge et ses dépendances

Toutes les dépendances de la forge sont déclarées en un seul endroit,
`roles/forge_preflight/defaults/main.yml`, et vérifiées par le rôle
`forge_preflight` avant toute installation. Une dépendance manquante devient un
échec d'assertion nommé, pas une erreur obscure trois rôles plus loin.

Le dépôt source avait la forme inverse : il installait `psmisc`, dont
`manageprofiles` a besoin pour `killall`, comme **dernière tâche** du playbook
d'installation — après les profils qui en dépendent.

| Côté | Déclaré | Vérifié par |
|---|---|---|
| Contrôle | version minimale d'`ansible-core`, collections par plan, paquets Python, commandes du PATH, constructeur d'image optionnel | `ansible_version`, `ansible-galaxy collection list`, un test d'import par paquet |
| Cible (WAS/IHS) | paquets OS par famille dont AIX, limites shell, répertoires requis, espace libre minimal, partage des binaires | `package_facts`, `stat`, `ansible_facts.mounts` |
| Cible (OpenShift) | groupes d'API, CRD de l'opérateur Liberty, namespace | `kubernetes.core.k8s_info` |

La portée suit `runtime.product` : le plan traditionnel a besoin de SSH et d'un
driver Jython déployé, le plan Liberty d'un point d'API et d'aucun SSH. Les deux
Execution Environments diffèrent pour la même raison — et `ee-was-traditional`
ne porte **ni Java ni Jython**, parce que le driver est une donnée qui part sur
la cible et s'exécute dans le `wsadmin` de la cible.

L'espace libre est vérifié avant une installation ou un fixpack à dessein : un
fixpack qui tombe en panne d'espace en cours d'application laisse l'installation
dans un état bien plus coûteux à récupérer qu'un playbook refusé.

## 15. CI : simulation sur k3s

La chaîne prouve trois choses, de la moins coûteuse à la plus coûteuse.

**Statique, sans cluster.** `yamllint`, `ansible-lint`, contrôles de syntaxe,
puis : `site-vars-drift` compare le SHA-256 de `00_site.yml` entre
environnements ; `model-matrix` valide chaque environnement, vérifie que la
production est refusée sans `-e model_allow_production=true` et passe une fois
acquittée, et que le JDK de diagnostic est refusé ; `pilot-render` rend un
datasource pour les trois phases.

**Toute la chaîne traditionnelle, contre un faux référentiel, sans cluster.**
`stub-unit` exécute `ci/run-stub-tests.sh`, qui fait tourner le vrai
`driver.py` et le vrai handler de cluster derrière un substitut de
`wsadmin.sh`. WAS ND ne peut pas être embarqué dans une image de CI — licence,
droits, plusieurs gigaoctets — mais presque rien de ce qui casse dans le plan
traditionnel n'est du comportement WAS. C'est la plomberie : validation des
arguments, fichier de payload, lancement, routage, read/plan/write, réponse
JSON, `changed` et `diff`. Tout cela tourne réellement. Vingt-six contrôles,
dont deux garde-fous qui cassent le build si des identifiants réapparaissent
sur une ligne de commande wsadmin ou si le fichier de propriétés n'est pas en
`0600`, et un qui vérifie que la synchronisation des nœuds ne part que sur un
vrai changement.

La plupart de ces contrôles sont la vie entière d'un membre de cluster : créé,
rejoué, vidé à poids 0, son port épinglé puis le port épinglé rejoué, supprimé,
et refusé quand le cluster n'existe pas ou quand deux JVM d'un même nœud
réclameraient le même port. Le handler des membres est le premier à porter une
**liste** et non un objet unique, et c'est là qu'une copie de dictionnaire de
surface dans le planificateur sautait silencieusement l'écriture pendant que le
`diff` annonçait le changement comme fait — pris ici, par un rejeu qui devait
annoncer aucun changement et ne le faisait pas.

**La même chaîne contre de vrais hôtes sur k3s.** Deux namespaces :

| Namespace | Contient | Pourquoi séparé |
|---|---|---|
| `was-sim-dmgr` | un pod Rocky 9 tenant le rôle du deployment manager | La DMGR détient le référentiel maître et le pousse |
| `was-sim-nodeagents` | deux pods Rocky 9 tenant le rôle de node agents | Un node agent reçoit. Autre zone de confiance |

Rocky Linux 9 parce que c'est l'équivalent librement redistribuable le plus
proche du RHEL du parc : même gestionnaire de paquets, même systemd, même
sémantique de `/etc/security/limits.d`. L'image est **standard** — aucune
dépendance à un registre, rien à maintenir. Les paquets, le driver Jython et le
substitut wsadmin sont tous mis en place par les mêmes rôles qui tourneront
contre le parc réel : la CI exerce donc le chemin de production, pas un chemin
spécial.

Il n'y a ni `sshd` ni clé privée dans ces pods. Ansible les atteint par le
plugin de connexion `kubernetes.core.kubectl`, via `pods/exec`.

`sim:configure` exécute le play trois fois : `--check --diff`, puis
application, puis à nouveau. **Le troisième passage doit reporter `changed=0`
sur chaque hôte.** Ce rejeu est la seule preuve réelle d'idempotence, et c'est
une affirmation que l'approche historique ne pouvait pas tenir : ses fichiers
témoins annonçaient « rien à faire » que la cellule corresponde encore ou non.

`sim:members` est l'axe vertical et le second rejeu. `sim:configure` construit
un membre par nœud, soit un cluster horizontal ; ce job lance
`traditional_cluster_members.yml` **seul** — être lançable séparément est tout
l'intérêt de l'avoir découpé — avec deux membres par nœud sur deux nœuds, soit
quatre JVM. Il vérifie ensuite la forme dans les mots du rôle lui-même, qu'aucun
couple de serveurs d'un même nœud ne détient le même port, qu'un compteur
au-dessus de la borne est refusé, et qu'un nom de membre imposé contre un
compteur de deux est refusé en nommant les deux sorties.

`sim:isolation` vérifie la frontière plutôt que de la décrire : l'identité CI ne
doit **pas** pouvoir faire d'exec dans `kube-system`, `ci` ou `default`, et la
frontière doit tenir - vérifiée par le **trafic**, et non en lisant les objets
de politique. [`ci/assert-network-boundary.sh`](ci/assert-network-boundary.sh)
démarre une écoute sur la cible, puis se connecte à travers la frontière : un
agent de nœud atteint le gestionnaire de déploiement sur le port autorisé, et
est refusé sur tout autre ; le gestionnaire ne peut pas atteindre un agent de
nœud ; un agent ne peut pas en atteindre un autre. Une NetworkPolicy existante
prouve qu'un objet YAML existe, pas que quoi que ce soit est bloqué - un
cluster dont le contrôleur de politiques est éteint contient les mêmes objets
et n'applique rien. Et vérifier le trafic ne demande que `pods/exec`, que
l'identité CI détient déjà : le test tourne sur un cluster construit depuis ce
dépôt, sans rien accorder à la main. Le ServiceAccount est lié par des
Roles namespacés, jamais par un ClusterRole, donc un token CI fuité n'atteint
exactement que deux namespaces jetables.

`sim:teardown` supprime les pods et laisse les namespaces : ce sont des
ressources d'infrastructure appliquées une fois, et une chaîne qui les supprime
se rend elle-même inexécutable.

## 16. Le lab d'installation : une VM KubeVirt

La simulation ci-dessus n'installe rien. Installation Manager a besoin d'un
endroit réel pour atterrir, et c'est une machine distincte : **une VM
KubeVirt**, `was-lab-01` dans le namespace `was-lab`, déclarée dans
[`ci/k3s/20-was-lab-vm.yml`](ci/k3s/20-was-lab-vm.yml).

**Pourquoi une VM et pas un pod de plus.** Installation Manager écrit dans les
répertoires d'installation, tient un registre d'installation, attend une vraie
arborescence et assez de disque, et `manageprofiles` attend un arbre de
processus qui fonctionne — il appelle `killall`. Un conteneur n'a pas cette
forme. Les pods de simulation sont du Rocky 9 d'origine sur `emptyDir`, sans
`sudo` et avec un stub wsadmin ; rien là-dedans ne pourrait porter une
installation IBM de 2,5 Go. KubeVirt et CDI tournent déjà sur le cluster, donc
la VM ne coûte rien de plus à exploiter et se détruit en supprimant un seul
namespace.

| Objet | Nom | Remarque |
|---|---|---|
| Namespace | `was-lab` | |
| DataVolume | `was-lab-disk` | Rocky 9 GenericCloud importée par CDI, 40 Gi |
| VirtualMachine | `was-lab-01` | 4 vCPU, 6 Gi — WAS 9.0 réclame 2 Gi au minimum et y est misérable |
| Service | `was-lab-01` | `22`, `9043`, `9080`, joignable depuis le cluster sans Route |
| Secret | `was-lab-cloudinit` | données cloud-init. **Pas dans ce dépôt** : il porte la clé publique SSH |

On la monte avec [`ci/k3s/make-lab-vm.sh`](ci/k3s/make-lab-vm.sh), qui construit
le Secret depuis la paire de clés présente sur le nœud, applique le manifeste,
attend l'import de l'image et affiche l'adresse. La destruction est
`kubectl delete ns was-lab`, et elle ne laisse rien derrière.

### Y entrer

**La VM tourne dans un pod, et ce pod n'est pas la porte d'entrée.** KubeVirt
l'enveloppe dans `virt-launcher-was-lab-01-xxxxx` ; un `kubectl exec` sur ce pod
vous dépose dans le conteneur virt-launcher, à côté du processus QEMU, pas dans
le Rocky invité. Installation Manager est inatteignable par ce chemin.

```bash
# Sur un noeud k3s, /usr/local/bin/kubectl est un LIEN SYMBOLIQUE VERS k3s, et
# ce wrapper lit /etc/rancher/k3s/k3s.yaml - possede par root, mode 0600 - sauf
# si KUBECONFIG dit autre chose. Sans cette ligne, kubectl echoue sur une erreur
# de permission qui ressemble a un cluster casse, la substitution ci-dessous
# rend une chaine vide, et toutes les commandes suivantes tournent en silence
# sur le noeud au lieu de la VM.
export KUBECONFIG=$HOME/.kube/config

kubectl -n was-lab get vmi,pod          # vmi was-lab-01 doit etre Running

IP=$(kubectl -n was-lab get vmi was-lab-01 -o jsonpath='{.status.interfaces[0].ipAddress}')
[ -n "$IP" ] || echo "pas d'adresse - ne rien lancer d'autre"
ssh -i ~/.ssh/was_lab ansible@"$IP"
```

`virtctl` éviterait la recherche d'adresse, mais il **n'est pas installé sur ce
nœud** — il n'y a que `kubectl` et `k3s`. `virtctl console` ne servirait de toute
façon à rien : cloud-init pose `ssh_pwauth: false`, `disable_root: true` et aucun
mot de passe. La clé est la seule entrée.

Les pods de job AWX tournent dans le cluster, donc
`was-lab-01.was-lab.svc.cluster.local` résout et c'est ce nom que l'inventaire
emploie. Depuis le nœud lui-même, passer `-e ansible_host=$IP`.

### Les médias, que rien ne télécharge

Aucun des deux artefacts ne s'obtient sans un IBMid, donc les deux sont déposés
à la main. Dans l'inventaire du lab les motifs sont **sur le contrôleur** et les
rôles recopient les archives ; sur le parc le média arrive par un partage monté
et les motifs restent vides.

| Artefact | Motif côté contrôleur (`group_vars/was_lab.yml`) | Où il atterrit sur la VM |
|---|---|---|
| Installation Manager | `/mnt/binaries/IBM/install_im/*.zip` | `/mnt/binaries/IBM/install_im` |
| WAS 9.0 for Developers | `/mnt/binaries/IBM/install_was90/*.zip` | `/mnt/binaries/IBM/install_was90` |
| Fix packs | `/mnt/binaries/IBM/fixes/*.zip` | un répertoire de dépôt par archive |

Chaque archive de fix pack est un dépôt Installation Manager à elle seule et
elles ne doivent pas être décompressées l'une sur l'autre : deux
`repository.config` dans un même répertoire et `imcl` lit celui qu'il trouve en
premier. Sous AWX le contrôleur est le pod de job, donc ces chemins doivent être
montés dans l'Execution Environment, sinon l'étape de dépôt ne trouve rien.

L'installation de base Developers donne **9.0.0.0**. Le niveau 9.0.5.x vient du
fix pack, qui est un job séparé — d'où `was_expected_version: "9.0.0.0"`.

### Remplir le dépôt local depuis IBM

Les zips 9.0.0.0 ne sont pas la seule entrée. Le dépôt composite ILAN en ligne
sert le niveau **courant**, donc Packaging Utility peut recopier du 9.0.5.x
directement dans le répertoire de média, après quoi la VM n'a plus jamais besoin
d'Internet. [`ci/k3s/lab-mirror-was.sh`](ci/k3s/lab-mirror-was.sh) fait
exactement cela, lancé depuis le nœud comme `make-lab-vm.sh` :

```bash
bash ci/k3s/lab-mirror-was.sh --check    # preconditions seules, ne change rien
bash ci/k3s/lab-mirror-was.sh            # la totalite
```

Il vérifie `KUBECONFIG`, la phase du VMI, la clé, le sudo sans mot de passe, la
version d'Installation Manager, l'espace libre et la sortie réseau **avant** de
demander quoi que ce soit. Puis il demande une seule fois l'IBMid via
`imcl -prompt` — le mécanisme qu'Installation Manager recommande lui-même quand
il refuse un dépôt — ce qui écrit un coffre chiffré sur la VM. Aucune exécution
ultérieure ne porte de secret, et le mot de passe n'apparaît ni dans une ligne
de commande ni dans l'historique du shell.

Cette invite interactive est la raison pour laquelle c'est un script et pas un
playbook : elle exige un TTY, et un pod de job AWX n'en a pas.

Deux choses à savoir. ILAN est la licence sous laquelle l'édition « for
Developers » est livrée ; la table IBM ne comporte aucune entrée « Developers »,
donc le composite est `V9WASILAN` et le dépôt individuel
`com.ibm.websphere.ILAN.v90`. Et un miroir pris sur le dépôt en ligne est du
**9.0.5.x, pas du 9.0.0.0** — `was_expected_version` doit donc suivre, sinon
l'assertion finale du job échoue sur une installation parfaitement saine.

### Installation Manager sur la VM

Le rôle d'installation lance `imcl` avec `become`, donc c'est une installation
**en mode administrateur** : le binaire appartient à root et `imcl` sous le
compte de service échoue sur `CRIMC1018E ERROR: Administrator privileges are
required`. Seul `version` passe sans privilèges. Tout le reste demande `sudo` :

```bash
IMCL=/app/binaries/InstallationManager/eclipse/tools/imcl

$IMCL version                                       # le seul appel qui ne demande rien
sudo $IMCL listInstalledPackages -long
sudo $IMCL listAvailablePackages -repositories /mnt/binaries/IBM/install_was90 -long
sudo $IMCL -c                                       # mode console
```

Les données d'agent et le registre d'installation sont sous
`/app/data/IM/agentdata`, pas sous `/var/ibm/InstallationManager`, parce que le
rôle passe `-dataLocation`. Un seul montage porte donc toute l'installation.

**Il n'y a aucun chemin par navigateur.** Installation Manager n'a pas
d'interface web ; `IBMIM` exige un serveur X, et les URL de dépôt de service
`ibm.com/software/repositorymanager/...` ne s'ouvrent pas davantage dans un
navigateur — elles ne sont consommables que par Installation Manager. Un dépôt
local *peut* en revanche être servi en HTTP par n'importe quel serveur web et
donné à `imcl` sous la forme `http://hote/depot/repository.config` : c'est la
seule place d'un navigateur dans ce tableau.

La même interrogation sans ouvrir de shell, qui est aussi la façon dont AWX
l'exécute :

```bash
ansible -i inventories/lab was_lab -m command \
  -a "/app/binaries/InstallationManager/eclipse/tools/imcl \
      listAvailablePackages -repositories /mnt/binaries/IBM/install_was90 -long"
```

L'offering id n'est jamais codé en dur. Les éditions ne diffèrent que par cet id
— `com.ibm.websphere.ND.v90`, `.BASE.v90`, `.DEVELOPERS.v90` — et le devenir
produit une erreur `imcl` qui ressemble à un problème de licence ; le rôle
demande donc au dépôt ce qu'il contient.

### Le workflow

| Nœud | Playbook | Ce qu'il fait |
|---|---|---|
| 1 | `lab_install_im.yml` | Installation Manager. Le job 2 ne part que si celui-ci réussit |
| 2 | `lab_apply_fixpacks.yml` | passe 1 — amène Installation Manager au niveau que WAS exige |
| 3 | `lab_install_was.yml` | WAS for Developers et le SDK, dans un seul appel `imcl` |
| 4 | `lab_apply_fixpacks.yml` | passe 2 — corrige ce que le nœud 3 vient d'installer |
| 5 | `lab_create_profiles.yml` | les profils — gestionnaire de déploiement, puis le nœud fédéré |
| 6 | `traditional_cluster.yml` | le cluster |
| 7 | `traditional_cluster_members.yml` | les serveurs d'application qu'il contient, vertical ou horizontal |

Les nœuds 6 et 7 sont deux job templates et non un seul parce que chacun est
rejouable seul — voir la section 18. Sur le lab, ils se lancent avec
`-e config_dmgr_hosts=dmgr`, cet inventaire ne déclarant aucun groupe
d'environnement.

Un seul job template, deux nœuds de workflow pour les fix packs. Cela ne
fonctionne que parce que le rôle **découvre** ce qui est installé au lieu qu'on
lui donne une liste : à la passe 1 seul Installation Manager est là, à la passe 2
tout l'est. Ne trouver aucun dépôt de fix pack est un résultat normal — le job
dit ce qu'il a trouvé, dit où déposer le média, et sort en vert.

Le nœud 3 vérifie `imcl` lui-même plutôt que de faire confiance au nœud 1 : un
job template peut être lancé seul, et l'échec doit nommer ce qui manque plutôt
que de mourir dans un appel shell.

## 17. Le nommage des objets WAS est une entrée, pas une convention

**Chaque nom dont une cellule est construite est une variable que vous
définissez.** La cellule, le cluster, le serveur d'application, le nœud du node
agent, le profil du deployment manager : chacun est déclaré soit dans
l'inventaire, soit répondu dans le survey AWX. Le dépôt ne compose un nom que
lorsque personne n'en a fourni, et la forme composée est un repli, jamais une
règle.

| Variable | Nomme | Motif de repli |
|---|---|---|
| `was_cell_name` | la cellule | `{{ was_channel_name }}_{{ was_env_upper }}` |
| `was_cluster_name` | le cluster | `Cluster{{ was_channel_upper[:3] }}` |
| `was_cluster_member_name` | le JVM serveur d'application | cluster + nœud + index |
| `was_node_name` | le nœud — dmgr ou node agent, par hôte | `{{ was_host_short }}Node` pour un agent |
| `was_dmgr_profile_name` | le profil du deployment manager | `Dmgr_{{ was_env_upper }}_{{ was_channel_name }}` |
| `was_profile_name` | le profil sur cet hôte | le motif dmgr, ou `AppSrv01` |
| `was_console_label` | le libellé de la console d'administration | `{{ was_channel_name }} {{ was_env_upper }}` |
| `was_jvm_shared_class_cache` | `-Xshareclasses:name=` | `{{ was_env_upper }}%g` |

### Où les définir

La précédence va du plus fort au plus faible, et Ansible l'applique :

1. **Réponse du survey AWX**, ou `-e` en ligne de commande. Les extra-vars
   dominent tout, donc une question de survey pour le nom du cluster est
   honorée quoi que dise l'inventaire.
2. **`host_vars/<hôte>.yml`** pour une machine — un nœud dont le nom ne suit
   pas la règle du site.
3. **`group_vars/<groupe>.yml`** pour une règle — `nodeagents.yml` pour tous
   les agents, un groupe d'environnement pour un environnement.
4. **Le motif** dans [`roles/model/vars/naming.yml`](ansible_collections/wasevo/websphere/roles/model/vars/naming.yml),
   atteint seulement quand les trois précédents se taisent.

Le mécanisme tient en une ligne par nom dans
[`roles/model/tasks/naming.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/naming.yml) :

```yaml
was_cluster_name: "{{ was_cluster_name | default(was_cluster_name_pattern, true) }}"
```

`set_fact` domine `group_vars`, donc sans ce `default()` cette tâche écraserait
en silence une surcharge délibérée — exactement le bug où une entrée
d'inventaire est ignorée et où personne ne s'en aperçoit avant que l'objet
existe sous le mauvais nom. Chaque nom publié est ensuite vérifié non vide et
sans espace, parce que `wsadmin` accepte un mauvais nom à la création et que
toute recherche ultérieure par nom échoue.

**Rien d'autre dans le dépôt ne compose un nom d'objet WAS.** Ces motifs
vivaient dans trois inventaires, écrits trois fois, avec le nom du cluster figé
à `ClusterEXT` dans deux d'entre eux. Trois copies d'une règle de nommage, ce
sont trois occasions de divergence, et la divergence se manifeste par une
cellule qui refuse de se fédérer.

### Une machine, deux rôles : comment le lab déclare une cellule ND

Une cellule ND, c'est un gestionnaire de déploiement plus au moins un nœud
fédéré. Le lab possède une seule VM, donc les deux profils y atterrissent.
Ansible exprime « une machine qui joue deux rôles » avec **deux entrées
d'inventaire** pointant vers le même `ansible_host` — pas avec une entrée dans
deux groupes, qui est le raccourci évident et qui ne marche pas ici.

| Entrée | Groupe | Ce qu'elle porte |
|---|---|---|
| `was-lab-01` | `was_lab` | l'installation — IM, WAS, les fix packs. Une seule fois : `imcl` prend un verrou |
| `was-lab-01-dmgr` | `dmgr` | le profil du gestionnaire de déploiement |
| `was-lab-01-node` | `nodeagents` | le profil managé — donc l'agent de nœud, et le membre de cluster, qui est le serveur d'application |

Pourquoi pas une entrée dans les deux groupes :

- [`roles/model/tasks/naming.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/naming.yml)
  décide le nom de profil et le nom de nœud d'après l'appartenance aux groupes.
  Un hôte dans `dmgr` **et** `nodeagents` est un gestionnaire de déploiement
  pour cette décision : le profil fédéré serait nommé d'après le dmgr et la
  fédération échouerait sur un nom de nœud déjà présent dans la cellule.
- `group_vars/dmgr.yml` et `group_vars/nodeagents.yml` définissent tous deux
  `was_profile_path` et `was_service_name`. Sur un hôte dans les deux groupes,
  l'un gagne silencieusement par ordre alphabétique de groupe.

**Deux bases de ports, pour la même raison.** Chaque template `manageprofiles`
alloue une douzaine de ports vers le haut depuis la base qu'on lui donne ; une
base unique pour deux profils sur une machine, c'est deux profils qui
réclament les mêmes ports. `group_vars/all/40_runtime.yml` déclare
`was_lab_dmgr_base_port` (30000) et `was_lab_node_base_port` (30100), et chaque
groupe de rôle en consomme une. `was_dmgr_soap_port` est **ancré sur la base du
dmgr** et non sur `was_base_port`, qui diffère désormais selon le rôle — sinon
un nœud fédéré chercherait le port SOAP du dmgr 100 ports trop haut. Il ne
reste de toute façon qu'un repli : `profile_dmgr` lit le profil créé et publie
`was_dmgr_soap_port_actual`, que `profile_nodeagent` préfère.

Où chaque nom est écrit, pour le lab :

| Nom | Fichier |
|---|---|
| cellule, cluster | `inventories/lab/group_vars/all/30_naming.yml` — ils sont communs à la cellule |
| profil et nœud du dmgr | `inventories/lab/group_vars/dmgr.yml` |
| profil, nœud, membre de cluster | `inventories/lab/group_vars/nodeagents.yml` |

Aucun code d'environnement n'y est écrit : `was_env_upper` et
`was_channel_name` sont publiés par le rôle `model` d'après les réponses du
formulaire, et un template de `group_vars` se résout au moment où il est lu,
c'est-à-dire après. **Attention à la précédence** : une réponse de formulaire
est une extra var et surclasse ces fichiers, et une question optionnelle
laissée vide arrive comme chaîne vide, que `default(..., true)` ramène au
**motif du rôle** — pas à la valeur de l'inventaire. Un run lancé depuis le
formulaire remplit donc ces questions avec les mêmes valeurs, ou accepte les
motifs.

### Standalone ou ND : la topologie est répondue, et c'est elle qui décide le profil

**Les binaires installés sont identiques dans les deux cas.** Même offre, même
répertoire d'installation, même ligne `imcl`. Ce qui diffère, c'est le template
sur lequel on pointe `manageprofiles` — raison pour laquelle la topologie est
une question du job de profil et non du job d'installation : la mettre sur le
formulaire d'install serait un décor qui ne change rien.

| `was_topology` | Template | Produit |
|---|---|---|
| `standalone` | `profileTemplates/default` | une cellule, un nœud, sa propre console. Pas de deployment manager, pas de nodeagent, **pas de cluster** |
| `nd` | `profileTemplates/management` + `serverType=DEPLOYMENT_MANAGER` | le deployment manager |
| `nd` | `profileTemplates/managed` | un nœud fédéré, ce qui donne un nodeagent |

[`roles/model/tasks/topology.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/topology.yml)
refuse toute autre valeur, dit ce que chacune construit, et publie
`was_can_cluster: false` pour standalone — un job de cluster refuse donc tôt au
lieu d'échouer dans `wsadmin`.

Elle est répondue et non déduite de la forme de l'inventaire, délibérément : un
hôte unique peut légitimement être un serveur standalone **ou** une cellule ND
à un nœud. C'est une intention, et une intention ne se devine pas.

### Le profil est un response file rendu

Chaque rôle de profil rend un response file `manageprofiles` depuis le modèle
et le passe avec `-response`. Un artefact relisible par hôte, au lieu de quinze
arguments dans une ligne de shell.

```
create                                          create
profileName=Dmgr_PREPROD_Extranet               profileName=AppSrv01
templatePath=.../profileTemplates/management    templatePath=.../profileTemplates/managed
serverType=DEPLOYMENT_MANAGER                   nodeName=<hote>Node
cellName=Extranet_PREPROD                       federateLater=false
nodeName=PDmgrNode                              dmgrHost=<le dmgr>
startingPort=30000                              dmgrPort=<son vrai port SOAP>
enableAdminSecurity=true                        dmgrAdminUserName=...
```

Le fichier est rendu à **chaque** exécution et supprimé ensuite. Un response
file conservé entre deux runs devient une seconde définition du profil, et
celle qui dérive est toujours celle qu'on lit. `profile_keep_response` le garde
quand une création a échoué et que l'entrée exacte compte plus que la propreté ;
il est en 0600 et la tâche est `no_log`, parce qu'il porte le mot de passe
d'administration tant qu'il existe.

Les ports : un `profile_dmgr_ports` / `profile_node_ports` /
`profile_standalone_ports` vide signifie `-startingPort` depuis
`was_base_port`. Rempli, c'est un `-portsFile` qui est rendu, clé par clé comme
`portdef.props` nomme chaque point d'écoute — ce que l'inventaire déclare est
ce qui est écrit, ni plus ni moins.

### Ce que le formulaire ne demande pas, délibérément

**L'hôte du deployment manager et son port SOAP.** L'inventaire sait déjà quel
hôte est le deployment manager ; le deployment manager lui-même sait sur quel
port il écoute. Demander à un opérateur de retaper l'un ou l'autre crée deux
sources qui peuvent se contredire, et la contradiction se manifeste par un nœud
qui refuse de se fédérer.

Donc `profile_dmgr` **lit** `properties/portdef.props` du profil qu'il vient de
créer et publie le vrai port SOAP, et `profile_nodeagent` fédère contre
celui-là. À noter que `was_dmgr_soap_port` dans `40_runtime.yml` vaut
`was_base_port + 5`, ce à quoi le parc source a abouti — `manageprofiles
-startingPort` ne promet aucun tel décalage, l'ordre d'allocation appartient au
template de profil. C'est donc une attente qu'on signale quand elle diverge,
pas une source de vérité.

Avant de fédérer, le nœud vérifie que quelque chose écoute sur ce port **depuis
le nœud**, pas depuis le contrôleur. Fédérer contre un deployment manager
éteint échoue dans `addNode` sur une exception qui ressemble à un problème
d'identifiants ; c'est refusé ici à la place, avec un message qui nomme la vraie
cause et dit où lire le vrai port.

**Les hôtes des nodeagents, leurs noms de nœud et leurs ports** viennent de
l'inventaire : les hôtes du groupe nodeagents, et `was_node_name` par hôte là où
le standard du site diffère. Un survey AWX est plat — il n'a pas de groupe
répétable — donc une liste de nœuds ne s'exprime pas en questions de survey. Le
formulaire ne porte qu'une surcharge optionnelle, qui s'applique à tous les
hôtes du run.

### Simuler, c'est un run en check, et rien d'autre

**« Simuler l'installation » veut dire `--check`** — ce qu'AWX propose sous
**Job type: Check** dans la fenêtre de lancement, et ce que la chaîne passe
directement. Cette collection n'a aucun drapeau de simulation à elle : un
second chemin de code est une seconde chose à maintenir vraie, et ce serait
celui que personne ne lance.

Les job templates étaient livrés avec `ask_job_type_on_launch` à faux, donc
Check n'était pas sélectionnable et la seule façon de répéter une installation
était de la faire. [`ci/awx/apply-survey.sh`](ci/awx/apply-survey.sh) l'active,
en même temps que le survey, de sorte que Run et Check soient tous deux
accessibles au lancement.

Ce que les rôles de profil font en check mode :

- les tâches `command` ne s'exécutent pas, donc `manageprofiles` n'est jamais
  appelé
- les refus durs — produit absent, deployment manager muet, profil non
  atterri — se retirent : dans un run en check ils décrivent un futur, pas un
  état
- les sondes en lecture seule gardent `check_mode: false`, donc
  `-listProfiles` et les `stat` tournent quand même et rapportent honnêtement
- chaque rôle affiche **ce qu'il passerait à `manageprofiles`**, rendu sur le
  contrôleur par `lookup('template', ...)`, qui n'écrit nulle part. Le mot de
  passe d'administration est masqué à l'affichage ; le fichier dans lequel il
  serait écrit est en 0600 et la tâche est `no_log`

`sim:profiles` exécute exactement cela contre les trois pods de simulation, où
il n'y a pas de WAS et où il n'est pas prévu qu'il y en ait, et vérifie le
response file rendu, parce que ce fichier est le contrat entre cette collection
et `manageprofiles` : un template `management` avec
`serverType=DEPLOYMENT_MANAGER` sur le deployment manager, un template
`managed` avec `dmgrHost` et `dmgrPort` sur chaque nœud, aucun template
`default` sur un nœud, un run standalone qui annonce ne pas pouvoir clusteriser
avec les deux rôles ND qui se retirent, une topologie `whatever` refusée avec un
message nommant les deux valeurs acceptées, le mot de passe masqué et jamais
dans le log — et, pour finir, que `/app/profiles` et `/app/data/profiles` sont
vides sur chaque hôte simulé après coup.

## 18. Le cluster et ses serveurs d'application

**Un membre de cluster est un serveur d'application.** Le même objet : un JVM,
créé sur un nœud fédéré et possédé par la cellule. `manageprofiles` n'en crée
jamais — le template managed produit un agent de nœud et rien d'autre — donc le
membre est ce qui transforme un nœud fédéré en nœud qui fait tourner une
application, et c'est un job distinct de celui du profil qui le porte.

### Vertical, horizontal, ou les deux : c'est la liste des membres qui décide

| Forme | Ce que c'est | Comment on la déclare |
|---|---|---|
| **horizontal** | un membre sur chacun de plusieurs nœuds | le nombre d'hôtes du groupe nodeagents |
| **vertical** | plusieurs membres sur un même nœud | `was_cluster_members_per_node` sur ces hôtes |
| **les deux** | le produit des deux, ce à quoi ressemble un parc réel | les deux lignes ci-dessus |

**Il n'existe nulle part de variable de « type de cluster »**, et c'est
délibéré. Un membre est un JVM sur un nœud ; la forme est une conséquence de la
liste des membres, jamais un commutateur qui sélectionne un mode. Deux membres
par nœud sur deux nœuds, ce sont quatre JVM, déclarés par une réponse et un
groupe d'inventaire — et le rôle annonce la forme qu'il a construite,
`4 member(s) over 2 node(s) — vertical and horizontal`, pour qu'un opérateur
voie que le nombre répondu a produit le cluster qu'il voulait.

Les noms viennent du même motif unique que tout autre objet WAS, dans
[`roles/model/vars/naming.yml`](ansible_collections/wasevo/websphere/roles/model/vars/naming.yml),
rendu une fois par index :
[`tasks/cluster_members.yml`](ansible_collections/wasevo/websphere/roles/model/tasks/cluster_members.yml)
boucle sur les index avec `was_cluster_member_index` comme variable de boucle —
la variable que le motif lit déjà — de sorte que rien ne compose une seconde
forme du nom, spécifique au vertical.

| Entrée | Portée | Surclasse |
|---|---|---|
| `was_cluster_members_per_node` | tout le run, depuis le formulaire | — |
| `was_cluster_member_names` | un nœud, une liste, dans l'inventaire | le compteur, y compris le nombre |
| `was_cluster_member_name` | un membre, dans l'inventaire ou le formulaire | le motif |

**Un nom imposé ne peut pas nommer plusieurs JVM.** Remplir le nom du serveur
d'application, répondre deux serveurs par nœud, et le run est refusé — parce
qu'ajouter un index à un nom choisi à la main inventerait une convention que
personne n'a demandée. Le refus nomme les deux sorties : déclarer
`was_cluster_member_names` comme liste, ou laisser le nom vide et laisser le
motif les numéroter. La décision se prend en comparant le nom publié à ce que
le motif produirait, donc un nom qui coïncide avec le motif — le lab écrit le
sien en entier — ne crée aucun conflit.

### Deux JVM sur un même nœud ne peuvent pas partager un port

Chaque membre est un JVM avec ses propres points d'écoute `WC_defaulthost`,
SOAP et ORB. Sur un cluster vertical, le second membre recopierait les ports du
premier, et WAS **enregistre cette configuration sans broncher** : le second
serveur échoue alors au démarrage, peut-être des heures plus tard, sur une
erreur d'adresse déjà utilisée — et la configuration qui a produit ça a l'air
correcte dans la console.

Le module passe donc `genUniquePorts=true` et laisse WAS allouer des ports
libres. On les épingle à la place avec `was_cluster_member_ports` par hôte,
indexé par nom de membre puis par nom de point d'écoute tel que
`serverindex.xml` l'orthographie, quand le plugin IHS ou une règle de pare-feu
exige un port prévisible. Seuls les points d'écoute réellement épinglés sont
relus et comparés, donc un membre qui n'en épingle aucun ne coûte aucune
lecture supplémentaire — et un port épinglé qui dérive est signalé comme
n'importe quel autre écart.

`ci/assert-member-ports.py` vérifie la propriété au lieu de la décrire : il lit
la fausse cellule que garde la simulation et casse le build si deux serveurs
d'un même nœud détiennent le même port.

### Une seule session wsadmin pour tout le cluster

Un démarrage de JVM wsadmin coûte 30 à 60 secondes, donc `was_cluster_member`
prend **toute la liste des membres** en un appel, et non un membre par appel.
Huit membres créés un par un, ce sont huit démarrages et six minutes de chauffe
de JVM pour quelques secondes de travail.

- `-firstMember` est géré par le module, pas par l'appelant. L'API WAS l'exige
  exactement une fois par cluster, sur l'appel qui fixe le template de serveur
  dont tous les membres suivants sont copiés, et le handler sait d'après ce
  qu'il a lu si le cluster est encore vide.
- Le `weight` est lu et réconcilié, donc un membre peut être vidé à 0 — plus
  aucune nouvelle requête — sans être supprimé.
- Les membres que la cellule détient et que l'appel ne nomme pas sont **laissés
  en place**. La suppression est un `state: absent` sur une liste explicite,
  jamais un effet de bord du fait de ne pas nommer quelque chose : un run limité
  à un nœud ne doit pas supprimer les membres de tous les autres.
- Demander des membres dans une cellule qui n'a pas ce cluster est un **refus
  en une phrase**, pas une pile d'appels. Un handler lève `ValueError` pour
  refuser une demande qu'il a comprise ; tout le reste garde son traceback,
  parce que c'est un défaut et non une réponse.

### Chaque étape est rejouable seule

**Un rôle, un playbook, un job template.** Corriger une seule chose après une
mise à jour doit coûter une session wsadmin, pas toute la chaîne — sinon le
correctif est une reconstruction, et personne ne le fait.

| Playbook | Rôle | Rejoue |
|---|---|---|
| `traditional_cluster.yml` | `was_cluster` | l'objet cluster |
| `traditional_cluster_members.yml` | `traditional/server_member` | les serveurs d'application qu'il contient |
| `traditional_config.yml` | — | importe les deux, dans l'ordre, et n'en définit aucun |

Chaque playbook **ne fait donc confiance à aucun nœud de workflow antérieur** :
il résout le modèle lui-même, dépose le driver Jython lui-même, et vérifie ses
propres préconditions. Un profil de gestionnaire de déploiement absent est
signalé comme « le job de profil doit tourner d'abord », pas comme une erreur
wsadmin trois couches plus bas — la même raison qui fait que le job 3 de
l'install vérifie `imcl` lui-même au lieu de croire le job 1.

`traditional_config.yml` ne porte plus la tâche de cluster en ligne. Il importe
les deux playbooks, ce qui maintient une définition unique de chaque étape : les
anciens `launch_*.sh` portaient chacun leur copie de la même construction de
cellule, et les copies divergeaient.

**Pourquoi le playbook des membres a deux plays.** Un nom de membre est
construit depuis le nom du **nœud**, et le nœud est le seul hôte qui connaisse
le sien — `was_node_name` peut être un template de `group_vars` qui ne se
résout qu'une fois `was_env_upper` publié par le modèle sur cet hôte. Les nœuds
publient donc d'abord leur liste de membres, sans collecter de facts et sans
rien toucher, puis le gestionnaire de déploiement lit
`hostvars[<nœud>].was_cluster_members` et les crée, là où vit la session
wsadmin unique. Un run limité au seul gestionnaire de déploiement ne peut pas
voir ces noms, et le rôle le dit au lieu de construire un cluster vide.

Le motif d'hôtes de chaque playbook est surchargeable. Par défaut, c'est
l'intersection d'un groupe d'environnement et du groupe du gestionnaire de
déploiement, pour que l'environnement reste une entrée de lancement ; le lab
n'a volontairement aucun groupe d'environnement — la même VM est construite
comme n'importe quel environnement — et passe `-e config_dmgr_hosts=dmgr`,
exactement comme le fait déjà `lab_create_profiles.yml` pour les rôles de
profil.

## 19. Les ressources de la cellule

Les rôles sont rangés par **familles d'API** - la liste des API qu'utilise une
application, qui est la façon dont une équipe demande un changement (« notre
messagerie », « notre persistance »). Une famille est un catalogue, jamais une
fusion : chaque rôle garde son playbook et son job template, rejouable seul,
et le playbook d'une famille importe ceux de ses rôles dans l'ordre.

| # | Famille | Rôles aujourd'hui | Playbook de famille | Ensuite |
|---|---|---|---|---|
| 0 | Socle de la cellule | cluster, membres (section 18) | `family_0_foundation.yml` | - |
| 1 | Services web et REST - JAX-RS, JAX-WS, JAX-RPC | policy sets | `family_1_web_services.yml` | attachements, avec le déploiement d'application |
| 2 | Persistance et données - JPA, JDBC | JDBC, JPA | `family_2_persistence.yml` | - |
| 3 | Composants d'entreprise - EJB, CDI, JTA/JTS | transactions et reprise par un pair, conteneur EJB et minuteurs, CDI | `family_3_enterprise.yml` | - |
| 4 | Messagerie et intégration - JMS | SIBus, JMS sur le bus et sur IBM MQ | `family_4_messaging.yml` | - |
| 5 | API propriétaires et étendues | SSL et signataires, sécurité et registre d'utilisateurs (les quatre types), alias J2C, bibliothèques partagées, cache dynamique, logging et HPEL | `family_5_extended.yml` | - |
| 6 | JMX et administration - PMI, MBeans | PMI | `family_6_management.yml` | - |
| 7 | MicroProfile | - | - | phase 2, le back-end Liberty |

Le déploiement d'application vient après toutes. La phase 1 a un rôle dans
chaque famille sauf MicroProfile, qui est la phase 2.

**L'ordre des dépendances, pas celui des familles.** Une datasource (famille 2)
présente un alias J2C (famille 5) : `traditional_config.yml` enchaîne donc les
étapes dans l'ordre où elles ont besoin les unes des autres, quelle que soit
leur famille - les numéros d'étape ci-dessous. Un playbook de famille lancé
seul compte sur ce que les autres familles ont déjà construit, et chaque rôle
refuse un prérequis absent en nommant le job qui le produit.

Chaque famille de ressources est son propre rôle, son propre playbook et son
propre job template, dans l'ordre où une cellule en a besoin - et chacune est
rejouable seule, pour la raison donnée en section 18. Elles sont créées par
défaut **à la portée du cluster**, ce qui suit les membres verticaux et
horizontaux construits juste avant ; une ressource nomme une autre portée quand
elle en a besoin.

| Étape | Playbook | Ressources | Famille d'API |
|---|---|---|---|
| 8 | `traditional_j2c.yml` | alias d'authentification J2C | 5 |
| 9 | `traditional_jdbc.yml` | fournisseurs JDBC et datasources | 2 |
| 10 | `traditional_shared_libraries.yml` | bibliothèques partagées | 5 |
| 11 | `traditional_sibus.yml` | bus d'intégration de services | 4 |
| 12 | `traditional_jms.yml` | ressources JMS, sur le bus et sur IBM MQ | 4 |
| 13 | `traditional_transactions.yml` | service de transactions et reprise par un pair | 3 |
| 14 | `traditional_ejb_container.yml` | conteneur EJB, cache et minuteurs | 3 |
| 15 | `traditional_cdi.yml` | CDI | 3 |
| 16 | `traditional_jpa.yml` | niveau et défauts JPA | 2 |
| 17 | `traditional_ssl.yml` | configurations SSL et signataires | 5 |
| 18 | `traditional_security.yml` | sécurité globale et registre d'utilisateurs | 5 |
| 19 | `traditional_policy_sets.yml` | policy sets des services web | 1 |
| 20 | `traditional_dynamic_cache.yml` | cache dynamique et cache de servlets | 5 |
| 21 | `traditional_logging.yml` | logging, trace et HPEL | 5 |
| 22 | `traditional_pmi.yml` | PMI | 6 |

### Alias d'authentification J2C

Les identifiants qu'une datasource, une fabrique de connexions JMS ou un membre
de bus présente. **À l'échelle de la cellule, toujours** : un alias vit dans la
configuration de sécurité de la cellule, donc il ne prend aucune portée, et une
datasource à portée cluster y fait référence par son nom. C'est aussi pourquoi
il vient en premier - une première construction n'a alors pas besoin d'un
second passage.

La déclaration est celle du modèle partagé - la couche 1 - et porte le **nom**
d'une variable, jamais un mot de passe :

```yaml
j2c_aliases:
  - name: as400ExtranetAlias
    user: wsextranet
    password_env: AS400_EXTRANET_PASSWORD
```

Le rôle lit cette variable dans l'environnement du contrôleur, exactement là où
une credential AWX la dépose. Un alias sans mot de passe est refusé avant
wsadmin, par le nom de la variable à remplir, parce qu'un alias créé avec un
mot de passe vide ne s'authentifie nulle part et que l'échec n'apparaîtrait
que des heures plus tard, sous la forme d'une base qui refuse une connexion.

**Le mot de passe ne peut pas être comparé.** WAS le stocke encodé et ne rend
rien qu'un plan pourrait comparer ; le module ne fait donc pas semblant :

| `j2c_password_policy` | Fait | Annonce |
|---|---|---|
| `on_create` (défaut) | pose le mot de passe à la création de l'alias, puis n'y touche plus | un changement seulement sur ce qui se compare - l'utilisateur et la description |
| `always` | écrit le mot de passe à chaque exécution | un changement à chaque exécution, parce qu'il a pu en avoir un |

**Faire tourner le mot de passe d'une base, c'est un rejeu de
`traditional_j2c.yml` avec `-e j2c_password_policy=always`** - aucun cluster,
aucune datasource, aucune application touchés. C'est pourquoi les alias sont un
rôle à part et non une étape du rôle JDBC.

Le mot de passe n'apparaît jamais dans ce que rend le module, donc ni dans un
diff ni dans un log ; il ne circule que dans le fichier de payload 0600 que le
module supprime. Les tests de la fausse cellule le vérifient : chaque réponse
du driver sur un alias, rotation comprise, est fouillée à la recherche du mot
de passe et ne doit pas le contenir. Et la fausse cellule refuse tout
simplement de servir un mot de passe stocké, parce que la vraie le rend encodé
- un handler qui le relirait passerait en CI et casserait sur une cellule.

### Fournisseurs JDBC et datasources

**Une déclaration, deux back-ends.** Une datasource est déclarée une fois, dans
le modèle partagé, et le back-end Liberty la rend déjà dans `server.xml`. Le
back-end traditionnel rend maintenant **la même** déclaration en arguments
wsadmin - c'est la couche 1 qui fonctionne, et non deux configurations tenues
à jour en parallèle.

```yaml
datasources:
  - name: as400Extranet
    jndi_name: jdbc/as400/extranet
    vendor: db2_i_toolbox
    driver_dir: /app/binaries/was90/jdbcprovider
    driver_jar: jt400.jar
    auth_alias: as400ExtranetAlias
    properties: { databaseName: EXTRANET, serverName: as400.example.internal }
    pool: { maxPoolSize: 30, minPoolSize: 5, connectionTimeout: 30s, maxIdleTime: 1800s }
```

**Le vendor est une intention, traduite par chaque back-end.** Le modèle
disait `vendor: db2` et le template Liberty écrivait `<properties.db2>`, qui
n'est pas un élément Liberty - pour `jt400.jar`, l'élément est
`<properties.db2.i.toolbox>`.
[`roles/model/vars/jdbc_vendors.yml`](ansible_collections/wasevo/websphere/roles/model/vars/jdbc_vendors.yml)
nomme désormais une fois la base et la famille de driver, et donne à chaque
back-end son rendu : l'élément Liberty, et le type de fournisseur et la classe
helper dont `createJDBCProvider` et `createDatasource` ont besoin. Le modèle
refuse un vendor qu'aucun back-end ne connaît, avant tout rendu.

[`plugins/filter/traditional.py`](ansible_collections/wasevo/websphere/plugins/filter/traditional.py)
fait le rendu traditionnel - en Python plutôt qu'en bloc Jinja, parce que ces
règles méritent d'être testées seules :

| Modèle partagé | WAS traditionnel |
|---|---|
| `vendor: db2_i_toolbox` | type `DB2 UDB for iSeries (Toolbox)`, helper `DB2AS400DataStoreHelper` |
| `maxPoolSize`, `minPoolSize` | `maxConnections`, `minConnections` |
| `connectionTimeout: 30s`, `maxIdleTime: 1800s` | `connectionTimeout: 30`, `unusedTimeout: 1800` - en secondes |
| `transactional: "false"` | propriété `nonTransactionalDataSource=true` |
| une clé de pool sans équivalent | **refusée**, et non ignorée |

Un réglage qui disparaît en silence d'un côté est une différence entre les deux
back-ends que personne n'a choisie : une clé inconnue de la table est donc
refusée. Toutes les erreurs d'une déclaration sont signalées en une fois.

**Ce que WAS accepte et ne devrait pas**, refusé avant toute écriture :

- un **type de fournisseur que la cellule ne propose pas**. Le handler liste
  d'abord les modèles de fournisseurs JDBC de la cellule ; une entrée fausse
  de la table échoue à son premier vrai run avec la liste de ce que la cellule
  propose, plutôt que dans `createJDBCProvider` sur une exception qui ne nomme
  ni l'un ni l'autre ;
- une **datasource dont l'alias J2C n'existe pas**. WAS l'accepte, et la
  datasource échoue à sa première connexion ;
- une **datasource sur un fournisseur absent** de cette portée.

En check run, les deux derniers sont un futur et non une absence : l'étape qui
les crée a tourné en check elle aussi.

**Deux comportements de WAS absorbés par les handlers.** Le classpath est un
attribut liste, et `AdminConfig.modify` **ajoute** à une liste au lieu de la
remplacer - un nouveau jar écrit par un simple modify laisserait l'ancien
devant lui dans le classpath, et l'ancien driver gagnerait. Il est vidé
d'abord, puis écrit ; un test de la fausse cellule vérifie que le jar a été
remplacé et non ajouté. Et seuls les réglages de pool et les propriétés qu'une
déclaration nomme sont relus et comparés : une datasource en porte des
dizaines à leur valeur WAS, et réinitialiser ceux que personne n'a déclarés
écraserait un réglage fait à dessein dans la console.

**Portée.** Le cluster par défaut ; une datasource déclare `scope:` pour une
autre - `cell`, ou `{type: server, node: ..., server: ...}`. Le rôle regroupe
par portée, une session wsadmin par module et par portée. À la création, les
fournisseurs passent d'abord ; à la suppression, les datasources d'abord, pour
que rien ne pointe jamais vers un driver disparu.

**Pas encore vérifié sur une vraie cellule** : les types de fournisseurs autres
que celui d'IBM i Toolbox, et les noms de classes helper. Ils sont consignés
dans la table des vendors, qui le dit ; c'est la vérification des modèles
ci-dessus qui transforme une entrée fausse en phrase au premier run du lab.

### Bibliothèques partagées

Déclarées dans le modèle partagé sous l'une de deux formes, et **les deux
back-ends rendent les deux** :

```yaml
shared_libraries:
  - name: appCommonLibrary        # un répertoire et un motif
    dir: /app/binaries/shared
    includes: "*.jar"
  - name: reportingLibrary        # ou une liste explicite, dans l'ordre
    jars: [/app/binaries/reporting/engine.jar, /app/binaries/reporting/fonts.jar]
```

**Un motif veut dire la même chose des deux côtés.** Liberty lit `dir` +
`includes` comme un fileset et le relit au démarrage. WAS traditionnel n'a
**aucun joker** dans le class path d'une bibliothèque : écrire le seul
répertoire donnerait une bibliothèque différente sur chaque back-end - une
différence que personne n'a choisie. Le rôle développe le motif sur le
gestionnaire de déploiement avec le module `find` - une lecture, donc un check
run le fait aussi - et transmet la liste exacte des jars, triée, parce que
`find` rend les fichiers dans l'ordre du système de fichiers et qu'un class
path qui se réordonne d'un run à l'autre se lirait comme un changement à
chaque fois. Un jar déposé dans le répertoire apparaît alors comme un écart au
run suivant, ce qui est aussi le comportement de Liberty, un redémarrage plus
tard.

Un motif qui ne trouve rien est **refusé** : une bibliothèque au class path
vide ne fournit rien, et les applications qui l'utilisent échoueraient à leur
premier chargement de classe. Le répertoire doit contenir les mêmes jars sur le
gestionnaire de déploiement que sur chaque nœud qui porte un membre - un
montage partagé, ou le déploiement des binaires applicatifs, le garantit
normalement.

Le class path est un attribut liste : il est vidé puis réécrit, comme le
classpath JDBC. Associer une bibliothèque à une application ou au class loader
d'un serveur n'est **pas** fait ici : cela relève du déploiement d'application,
qui vient en dernier.

La simulation exerce les deux formes. `sim:configure` dépose deux jars **et un
README** dans le répertoire de la bibliothèque à motif, et vérifie qu'elle
contient exactement les deux jars - le motif respecté, et non le répertoire
pris en bloc.

### Bus d'intégration de services

La messagerie intégrée de WAS traditionnel, sur laquelle tourne JMS avec le
fournisseur de messagerie par défaut. **Traditionnel uniquement** : Liberty n'a
pas de bus, et y migrer veut dire un broker externe (section 10) ; cette
déclaration vit donc dans la partie traditionnelle du modèle, et non dans la
couche commune.

```yaml
sibuses:
  - name: OrdersBus
    members:                      # omis : le cluster du run
      - { cluster: ClusterEXT01, store: file, policy: HA }
    destinations:
      - { name: OrdersQueue, max_failed_deliveries: 5, exception_destination: OrdersDeadLetters }
      - { name: OrdersDeadLetters }
      - { name: PricesTopic, type: topic_space, reliability: RELIABLE_NONPERSISTENT }
```

**Un bus, une session.** `was_sibus` prend le bus, les membres qui portent ses
moteurs de messagerie et les destinations qu'il transporte, et les réconcilie
en une seule session wsadmin, dans l'ordre où ils dépendent les uns des
autres. Un bus qui ne nomme aucun membre prend le cluster du run. La politique
de moteur dit comment le cluster fait tourner ses moteurs : `HA`, un moteur qui
bascule entre les membres ; `SCALABILITY`, un moteur par membre - c'est là que
les membres verticaux de la section 18 commencent à compter pour la
messagerie.

**Ce qu'un run ne fait jamais : recréer un moteur.** Le magasin de messages
d'un membre et la politique de son moteur sont fixés à la création du moteur.
Changer l'un ou l'autre veut dire retirer le membre et le rajouter, ce qui
**détruit tous les messages que le moteur contient**. Un magasin déclaré qui
diffère du magasin réel est donc signalé par un avertissement Ansible et laissé
tel quel - `changed` reste à faux, puisque le run ne l'a pas changé, et
l'avertissement dit pourquoi. Perdre des messages doit être une décision que
quelqu'un prend, pas un effet de bord d'un rejeu. Un test de la fausse cellule
déclare un magasin en base sur un moteur à magasin fichier, et vérifie que le
moteur n'a pas été recréé.

La politique de moteur est appliquée à l'ajout d'un membre cluster et n'est
**pas** relue : elle vit dans les politiques du gestionnaire HA du groupe de
coordination, pas sur le membre, et un plan qui la comparerait comparerait une
supposition.

Refusé avant toute écriture : un bus sans membre - aucun moteur, donc aucun
point de file et rien pour porter un message ; une **destination d'exception**
qui n'est pas une destination du bus - WAS accepte n'importe quelle chaîne, et
les messages en échec n'ont alors nulle part où aller ; et toute valeur que
WAS contraint - niveau de fiabilité, politique de moteur - mal orthographiée,
avec la liste des valeurs acceptées. `state: absent` supprime le bus, ses
membres, leurs moteurs et leurs messages, et n'est jamais implicite.

**Pas encore vérifié sur une vraie cellule** : les arguments
d'`addSIBusMember` et de `createSIBDestination`, et la lecture du magasin via
le moteur du membre. Ils suivent la référence AdminTask ; c'est le run du lab
qui les prouvera.

### Ressources JMS

Fabriques de connexions, files, sujets et activation specs - les quatre sortes
dont un bean orienté message a besoin - sur le fournisseur de messagerie par
défaut, dont les ressources tournent sur le bus de l'étape précédente.

```yaml
jms:
  connection_factories: [{ name: OrdersCF, jndi_name: jms/ordersCF, bus: OrdersBus }]
  queues:               [{ name: OrdersQueue, jndi_name: jms/orders, queue: OrdersQueue, bus: OrdersBus }]
  topics:               [{ name: PricesTopic, jndi_name: jms/prices, topic_space: PricesTopic, topic_name: eur, bus: OrdersBus }]
  activation_specs:     [{ name: OrdersAS, jndi_name: jms/ordersAS, destination_jndi: jms/orders, bus: OrdersBus }]
```

**Un handler, une table par fournisseur.** Les quatre sortes sont la même idée
sur le fournisseur par défaut et sur IBM MQ ; ce qui diffère, ce sont les
verbes AdminTask et les attributs. `was_jms` porte une table par fournisseur :
IBM MQ, ci-dessous, est une table et non un second handler. Les
ressources sont regroupées par portée et par fournisseur, une session wsadmin
par groupe, relues par les verbes `show*` - qui aplatissent ce qu'une
ressource JMS range dans des jeux de propriétés - et comparées sur les champs
que la déclaration nomme.

**Ce que WAS accepte et ne devrait pas**, refusé avant toute écriture :

| Erreur | Ce qu'en fait WAS |
|---|---|
| une file JMS dont la destination de bus est absente, ou est un espace de sujets | l'enregistre ; le premier envoi échoue |
| un sujet JMS sur autre chose qu'un espace de sujets | l'enregistre ; la première publication échoue |
| une activation spec qui écoute un JNDI qu'aucune file ni aucun sujet ne porte, ou du mauvais type | le bean orienté message se déploie, démarre, et ne reçoit jamais rien |
| un alias J2C inexistant | la première connexion échoue |
| deux ressources sur le même JNDI | la recherche rend celle liée en dernier |

Une activation spec à portée cluster peut écouter une file déclarée à portée
cellule - WAS résout les noms JNDI à travers les portées - donc le rôle
transmet à chaque groupe la liste complète des files et sujets déclarés, et
cette configuration est acceptée ; un test de la fausse cellule le vérifie. En
check run, le bus et ses destinations peuvent ne pas exister encore, puisque
l'étape du bus a tourné en check elle aussi, et les contrôles du bus se
retirent. À la création, les destinations passent avant ce qui y fait
référence ; à la suppression, ce qui écoute passe avant ce qu'il écoute.

### JMS sur IBM MQ

Le même rôle, le même playbook, les quatre mêmes sortes : une ressource dit
`provider: mq` et nomme un gestionnaire de files au lieu d'un bus. Ce que
partagent toutes les fabriques et activation specs d'un run - le gestionnaire
de files et le moyen de le joindre - se déclare une fois, la clé propre d'une
ressource l'emportant :

```yaml
jms:
  mq_connection: { qmgr: QM1, transport: CLIENT, host: mq.example, port: 1414, channel: APP.SVRCONN }
  connection_factories: [{ name: PaymentsCF, jndi_name: jms/paymentsCF, provider: mq, type: QCF }]
  queues:               [{ name: PaymentsQueue, jndi_name: jms/payments, provider: mq, queue: PAYMENTS.IN }]
  topics:               [{ name: RatesTopic, jndi_name: jms/rates, provider: mq, topic_name: rates/eur }]
  activation_specs:     [{ name: PaymentsAS, jndi_name: jms/paymentsAS, provider: mq, destination_jndi: jms/payments }]
```

Dans le handler, IBM MQ est une seconde table, les verbes de
`WMQAdminCommands` (`createWMQConnectionFactory`, `createWMQQueue`,
`createWMQTopic`, `createWMQActivationSpec`, et leurs list, show, modify et
delete). Le `max_concurrency` d'une activation spec est le `maxPoolSize` WMQ,
le pool de sessions serveur, à 10 par défaut comme sur le bus.

**Seul ce que la ressource déclare est comparé.** WAS remplit les attributs de
connexion MQ que personne n'a posés - un hôte, le port 1414, un canal - et les
rend à la lecture. Les comparer à un champ non déclaré annoncerait un
changement à chaque rejeu ; la fausse cellule les remplit comme WAS, et un
test vérifie qu'un rejeu reste à `changed=false`.

**Refusé avant toute écriture**, en plus de ce que refusent les deux
fournisseurs : un transport `CLIENT` sans `host` ni `connection_list` - WAS
l'enregistre, et la première connexion échoue. Dans le modèle, une ressource
MQ qui nomme un bus, une file MQ sans file, un sujet MQ sans chaîne de sujet.

**Pas encore prouvé** : les noms de paramètres viennent de la référence des
commandes IBM ; que les verbes `show*` les rendent sous les mêmes clés est une
hypothèse, que le premier run sur une vraie cellule confirmera. La simulation
déclare une file MQ à portée cellule et une activation spec à portée cluster
qui l'écoute ; aucun gestionnaire de files n'y tourne, configurer une
ressource ne connecte rien.

### Réglages de serveur : transactions, conteneur EJB, CDI, JPA

Les familles 3 et 2 ne sont pas des ressources que la cellule porte une fois ;
ce sont des réglages que porte chaque serveur d'application - son service de
transactions, son conteneur EJB, sa JVM, son service JPA. Quatre rôles, un
module, `was_server_settings`, et un handler : chaque rôle traduit une
intention en attributs WAS, le module les applique à chaque serveur de la
cible en une session wsadmin.

```yaml
transactions:   { total_timeout: 2m, maximum_timeout: 5m, log_root: /shared/tranlog, peer_recovery: true }
ejb_container:  { cache_size: 3000, timers: { datasource_jndi: jdbc/ejbTimers, poll_interval: 5m } }
cdi:            { implicit_bean_archives: false }
jpa:            { spec_level: "2.1", provider: eclipselink, jta_datasource: jdbc/orders, non_jta_datasource: jdbc/reporting }
```

**La cible est lue dans la cellule.** Une cible cluster désigne les membres
que la cellule porte maintenant, pas une liste calculée par le run : un
membre ajouté depuis le dernier run est rattrapé par un rejeu, et aucun n'est
oublié parce que le run ne le connaissait pas. Une topologie sans cluster
nomme son serveur, `<rôle>_target: {node, server}`.

**Redémarrage listé, jamais effectué.** Ces réglages s'appliquent au démarrage
du serveur. Le module rend `restart_required` - les serveurs dont la
configuration a changé - et les signale ; il ne redémarre rien. Les quatre
rôles passent en dernier dans `traditional_config.yml` : un seul redémarrage
les prend tous.

**Les noms d'attributs sont vérifiés auprès de la cellule.** Avant toute
écriture, chaque attribut déclaré est cherché dans `AdminConfig.attributes`
pour son type, et un nom inconnu est refusé avec la liste des noms valides.
C'est aussi la garde pour les noms que la référence de scripting IBM ne
montre pas (`enableHA` sur le cluster, les deux attributs de datasource par
défaut JPA, pris dans `cluster.xml` et `server.xml`) : le premier run sur une
vraie cellule les confirme, ou refuse avant d'écrire.

**Ce que WAS accepte et ne devrait pas**, refusé avant toute écriture :

| Erreur | Ce qu'en fait WAS |
|---|---|
| une durée de vie de transaction au-dessus de `maximum_timeout` | la plafonne sans rien dire |
| la reprise par un pair avec chaque journal sous son propre profil | l'accepte ; le membre survivant ne peut pas lire le journal du membre tombé, et la reprise échoue quand on en a besoin |
| des minuteurs EJB persistants sur plusieurs membres, sans datasource partagée ni ordonnanceur dédié | chaque membre garde sa propre base de minuteurs ; un minuteur créé au démarrage se déclenche une fois par membre |
| un ordonnanceur dédié avec une datasource ou un préfixe de tables de minuteurs | ignore la datasource |
| un fournisseur JPA qui n'implémente pas le niveau déclaré | le serveur démarre, chaque unité de persistance échoue |
| un défaut JTA sur une datasource déclarée non transactionnelle, ou l'inverse | l'unité de persistance écrit hors de la transaction, ou y enrôle ce qui devait en rester dehors |
| une datasource de minuteurs ou JPA que la cellule n'a pas | lie le nom ; le premier usage échoue |

**La reprise par un pair** demande `log_root` sur un stockage que tous les
membres montent ; le journal de chaque serveur va dans
`<log_root>/<cellule>/<nœud>/<serveur>` - le handler remplace `{node}` et
`{server}` pour chaque serveur. Déplacer le journal d'un serveur qui porte des
transactions en doute les perd : changer `log_root` cluster arrêté ou drainé.

### Sécurité : les quatre registres d'utilisateurs

`security` configure l'un des quatre registres que WAS propose, le rend actif,
et règle la sécurité administrative, applicative et Java 2 - un rôle, un
module, `was_security`, une session wsadmin.

```yaml
security:
  app_security: true
  registry:
    type: ldap                      # federated | ldap | localos | custom
    primary_admin_id: wasadm
    ldap:
      server_type: ACTIVE_DIRECTORY
      hosts: [ad1.example.com:636, ad2.example.com:636]
      base_dn: dc=example,dc=com
      bind_dn: cn=was-bind,ou=services,dc=example,dc=com
      bind_password_env: LDAP_BIND_PASSWORD
      ssl: true
```

| Type | Ce que c'est | Ce qu'il demande |
|---|---|---|
| `federated` | celui du profil : un référentiel fichier, realm `defaultWIMFileBasedRealm` | l'administrateur, le realm |
| `ldap` | un LDAP autonome, hôtes dans l'ordre de bascule | type de serveur, base DN, hôtes ; un bind DN avec la variable qui porte son mot de passe ; TLS |
| `localos` | les utilisateurs du système d'exploitation | une cellule sur un seul hôte |
| `custom` | une classe à vous qui implémente `UserRegistry` | la classe, dans le class path de chaque processus ; ses propriétés |

**Écrit avec les verbes IBM, relu dans la configuration.**
`configureAdmin<type>UserRegistry` configure le registre et, avec
`-verifyRegistry`, fait vérifier par WAS que l'administrateur y existe avant
d'enregistrer ; `setAdminActiveSecuritySettings` l'active. Ce qu'ils ont écrit
est relu dans `security.xml` par AdminConfig, et c'est ce qu'un rejeu compare.
Les hôtes de bascule LDAP et les propriétés du registre personnalisé sont mis
en conformité par AdminConfig, les verbes ne posant qu'un hôte et aucune
liste.

**Le mot de passe de bind** vient d'un credential, par le nom de la variable
qui le porte, comme celui d'un alias J2C, et n'apparaît dans aucun résultat :
`security_password_policy: on_create` l'écrit avec la configuration LDAP,
`always` à chaque run - la rotation.

**Ce que WAS accepte et ne devrait pas**, refusé avant toute session :

| Erreur | Ce qu'en fait WAS |
|---|---|
| la sécurité administrative coupée | sert toute requête d'administration sans authentification |
| un registre rendu actif sans son administrateur | enferme dehors tous les administrateurs au démarrage suivant |
| un LDAP sans TLS (sauf `allow_plaintext: true`) | envoie en clair le mot de passe de bind et celui de chaque utilisateur |
| un bind DN sans la variable qui porte son mot de passe | se lie avec un mot de passe vide, et échoue plus tard |
| des réglages d'un autre type de registre | les garde, et les ignore |
| `localos` sur une cellule dont les nœuds tournent sur plusieurs hôtes (lu dans la cellule) | vérifie chaque mot de passe auprès du système du serveur qui répond |

**Toute la cellule redémarre** pour qu'un changement de sécurité s'applique -
le gestionnaire de déploiement, les agents de nœud, les serveurs. Le module le
dit et ne redémarre rien. Après un changement de registre, `was_admin_user`
doit être un utilisateur du nouveau registre : le rôle prévient quand ce n'est
pas son administrateur.

### Configurations SSL et signataires

`ssl` gère les configurations SSL à la portée cellule ou nœud - magasin de
clés, magasin de confiance, protocole, force de chiffrement, authentification
du client - et les certificats signataires dont leurs magasins de confiance
ont besoin. `was_ssl_config`, une session.

```yaml
ssl:
  configs:
    - alias: CellDefaultSSLSettings
      scope: cell
      keystore: CellDefaultKeyStore
      truststore: CellDefaultTrustStore
      protocol: TLSv1.2
      security_level: HIGH
  signers:
    - alias: corp-ldap-ca
      host: ad1.example.com
      port: 636
```

**Avant la sécurité**, dans la chaîne : un LDAP sur TLS est approuvé par un
signataire que ce rôle récupère avec `retrieveSignerFromPort`. Un signataire
se compare par son alias ; un pair qui a changé d'émetteur est un signataire
déclaré absent, puis présent.

Refusé avant toute session : un protocole qui négocie sous TLS 1.2 -
`SSL_TLS`, `SSL_TLSv2`, `TLS`, `TLSv1`, `TLSv1.1`, tout SSL ; ceux acceptés
sont `TLSv1.2`, `TLSv1.3` et `TLSv1.2,TLSv1.3` - le niveau de sécurité `LOW`
ou `CUSTOM`, et la suppression d'une configuration par défaut du profil.
Refusé par la cellule : un magasin de clés que la portée n'a pas, les magasins
venant du profil ou d'une procédure de certificats que ce rôle ne remplace
pas.

Quand `dynamicallyUpdateSSLConfig` est coupé dans la cellule, le module liste
la cellule à redémarrer.

### Cache dynamique, logging et HPEL, PMI

Trois intentions de plus sur `was_server_settings`, appliquées à chaque
serveur de la cible lue dans la cellule, avec les serveurs à redémarrer
listés - le même mécanisme que les transactions, voir la section précédente.

```yaml
dynamic_cache: { enabled: true, cache_size: 3000, disk_offload: true, disk_offload_root: /var/was/dynacache }
logging:       { mode: hpel, trace_spec: "*=info", repository_root: /var/was/logs, log_max_size: 500, log_max_age: 72h }
pmi:           { enabled: true, statistic_set: extended }
```

| Erreur | Ce qu'en fait WAS |
|---|---|
| des membres partageant un répertoire de déchargement disque | chacun écrase les fichiers de cache des autres - le rôle ajoute `<nœud>/<serveur>` à la racine |
| un réglage de déchargement disque sans `disk_offload: true` | le garde, ne s'en sert jamais |
| un réglage de l'autre mode de logging | le garde, ne s'en sert jamais |
| une spécification de trace qui n'est pas `<composant>=<niveau>` | démarre le serveur avec |
| PMI `custom` | demande une spécification compteur par compteur que ce rôle ne porte pas |

`hpel` allume le service HPEL et éteint le logging basique en un seul
changement, comme la procédure IBM ; `*=all`, `*=finest`, `*=finer` et
`*=fine` sont acceptés avec un avertissement. L'attribut de spécification de
trace HPEL (`startupTraceSpec`) est pris dans `server.xml` ; le handler le
vérifie, comme chaque nom, auprès d'`AdminConfig.attributes` avant d'écrire.

### Policy sets des services web

`policy_sets` importe des policy sets par défaut du produit et les copie pour
ajuster les copies - `was_policy_set`, les verbes PolicySetManagement, une
session.

```yaml
policy_sets:
  - { name: WSHTTPS default, from_default: WSHTTPS default }
  - name: Corporate HTTPS
    copy_of: WSHTTPS default
    policies: { WSAddressing: { enabled: true } }
```

**Un défaut ne s'ajuste jamais sur place** : le prochain import remettrait la
version du produit. Des policies sur un set `from_default` sont refusées, de
même qu'une copie déclarée avant sa source. **Les attachements relèvent du
déploiement d'application**, la dernière étape : un set encore attaché à une
application est refusé à la suppression, et les applications sont nommées.

**Pas encore confirmé sur une vraie cellule** : le format dans lequel
`getPolicySet` et `getPolicyType` rendent leurs propriétés. Le handler les lit
comme `{clé=valeur, ...}`, la façon dont wsadmin imprime des `Properties` Java.

## 20. AWX

AWX tourne dans k3s sur l'hôte Ubuntu, déployé par l'AWX Operator, en version
figée. Voir [`ci/awx/README.md`](ci/awx/README.md).

**Aucun `sudo`.** Le `~/.kube/config` du compte est lisible, donc toute
l'installation passe par l'API Kubernetes ; Ansible lui-même est installé par
utilisateur avec `pipx`.

Deux pièges à la première installation, tous deux corrigés dans les manifests :

- `gcr.io/kubebuilder/kube-rbac-proxy` a été **retiré par Google** — le dépôt a
  disparu, pas seulement le tag — donc le pod de l'opérateur reste en
  `ImagePullBackOff` d'origine. La kustomization le redirige vers
  `quay.io/brancz/kube-rbac-proxy`, le domicile amont du composant.
- Appliquer l'opérateur et la ressource `AWX` dans une seule kustomization est
  une course : la CR est rejetée avec `no matches for kind AWX` avant que la CRD
  ne soit établie. D'où l'application en deux étapes.

`pipx install ansible` n'expose que `ansible-community` ; c'est `--include-deps`
qui met `ansible-playbook` dans le `PATH`.

Le mot de passe admin est généré par l'opérateur dans un Secret. Rien dans ce
dépôt ne le porte.

### Une cellule sur k3s : gestionnaire de déploiement et deux nœuds fédérés

Un workflow AWX dédié, **WAS cell - deployment manager and two federated
nodes**, construit une cellule à partir de rien sur le cluster k3s - rien
n'est lancé à la main, et il s'arrête au cluster : pas de JDBC, pas de JMS,
pas de changement de sécurité.

| Job | Playbook | Ce qu'il fait |
|---|---|---|
| 1 | `cell_machines.yml` | trois machines virtuelles KubeVirt, par l'API Kubernetes depuis le pod du job |
| 2 | `cell_media.yml` | le média Installation Manager et WAS, copié depuis la VM du lab |
| 3 | `lab_install_im.yml` | Installation Manager sur chaque machine |
| 4 | `lab_install_was.yml` | WAS sur chaque machine |
| 5 | `lab_create_profiles.yml` | le gestionnaire de déploiement, démarré ; puis chaque nœud fédéré, un à la fois |
| 6 | `traditional_cluster.yml` | le cluster |
| 7 | `traditional_cluster_members.yml` | un serveur d'application par nœud - un cluster horizontal de deux |
| 8 | `traditional_start.yml` | les agents de nœud et les membres démarrés ; ce qui tourne est laissé tel quel |
| 9 | `cell_console.yml` | la console sur l'adresse du nœud, vérifiée par elle |

Le formulaire est celui du workflow du lab : l'environnement (`poc`), le canal
(`Extranet`), la topologie (`nd`). Ils font les noms - cellule `Extranet_POC`,
cluster `ClusterEXT`, nœuds `<machine>Node`, membres
`ClusterEXT_<machine>Node_01`. L'inventaire, `inventories/cell`, nomme les
machines et rien d'autre.

**La console** : `http://lab.example.com:30000/ibm/console`. Le port 30000 est un
NodePort vers le `WC_adminhost` du gestionnaire de déploiement ; la connexion
redirige ensuite vers HTTPS sur `WC_adminhost_secure`, publié sous son propre
numéro (9043) sur la même adresse par le répartiteur de services du cluster.
Les deux ports sont lus dans le profil, pas supposés.

**Ce qui l'a rendu possible**, et resservira :

- `roles/platform/kubevirt_vms` - une machine par hôte d'inventaire, son
  disque importé une fois et jamais plus, un Service headless pour que chaque
  port WAS de la machine soit joignable sous un nom DNS stable, la clé du
  credential machine d'AWX installée par cloud-init. La machine résout son
  propre nom vers sa propre interface - derrière le masquerade de KubeVirt,
  l'adresse du pod ne lui est pas locale.
- `roles/platform/cell_media` - le dépôt WAS vient d'IBM derrière un IBMid ;
  la VM du lab le détient, donc la cellule le copie depuis elle par un serveur
  HTTP éphémère au lieu de redemander l'IBMid.
- `roles/traditional/server_start` - démarre le gestionnaire de déploiement,
  les agents de nœud et les membres dont le pid n'est pas vivant, et rien
  d'autre. Le rôle du profil du gestionnaire de déploiement le démarre
  désormais : un nœud ne peut pas se fédérer sinon, et rien ne le démarrait.
- Les rôles de profil prennent les ports par défaut du produit quand
  l'inventaire ne donne pas de port de base (`defaultPorts=true`) : un profil
  par machine n'a besoin de rien d'autre.

**L'accès au cluster** est un ServiceAccount, `awx/awx-cell-platform`
(`ci/k3s/30-awx-cell-platform.yml`) : créer, lire et modifier des namespaces,
machines virtuelles, disques, Secrets et Services - pas de suppression. AWX
tient son jeton comme credential Kubernetes. **L'administrateur WAS** est
`wasadmin`, son mot de passe généré une fois dans le Secret
`awx/was-cell-admin`, jamais dans le dépôt :

```sh
kubectl -n awx get secret was-cell-admin -o jsonpath='{.data.password}' | base64 -d
```

Tout ce qu'AWX contient est déclaré par `ci/awx/apply-cell-workflow.sh`, lancé
depuis le nœud.

### Ce que contient AWX est déclaré, pas cliqué

[`ci/awx/apply-templates.sh`](ci/awx/apply-templates.sh) crée les job templates
qui construisent une cellule et les chaîne dans le workflow dans l'ordre ; il
est rejouable, trouvant chaque objet par son nom et le corrigeant. Un job
template est de la configuration — quel playbook, quel inventaire, quelle
credential, si `Job type` est sélectionnable — et le cliquer signifie que
personne ne peut dire ce qu'AWX est censé contenir. C'est ainsi que trois
templates existaient et que les trois qui construisent une cellule manquaient.

Il déclare aussi le type de credential de l'administrateur WAS, pour que
`was_admin_user` et `was_admin_password` arrivent au playbook en extra vars
injectées — chiffrées au repos, masquées en sortie — au lieu de figurer en
clair dans les `extra_vars` d'un template. Il ne crée aucune credential : un
mot de passe ne vient pas d'un dépôt.

**AWX valide `playbook` contre la dernière mise à jour réussie du projet**, et
non contre le dépôt ; le script met donc le projet à jour et l'attend avant de
nommer un playbook. Un playbook poussé depuis cette mise à jour est sinon
refusé par `Playbook not found for project.`, qui ressemble à une faute de
chemin et n'en est pas une.

### Résolu : AWX exécute les jobs sur ce Kubernetes, en 24.6.1

> **Il n'y a rien vers quoi monter, et rien ne l'exigeait.** Le 31 octobre
> 2026, la mise à jour d'inventaire 49 et la commande ad hoc 52 (`ping` sur
> les trois hôtes du lab) ont réussi sur AWX 24.6.1, receptor 1.4.8,
> Kubernetes v1.37.0+k3s1.
>
> Une note précédente accusait l'attache **SPDY** de receptor et réclamait une
> montée de version d'AWX. Les deux moitiés étaient fausses, et ont été
> vérifiées :
>
> - ce cluster sert encore SPDY : `kubectl exec` et `kubectl attach -i` avec
>   `KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false` fonctionnent, l'attache portant
>   bien stdin jusqu'au pod ;
> - aucune montée n'existe : awx-operator 2.19.1 (AWX 24.6.1) reste la
>   dernière version, et tous les receptor jusqu'à 1.6.9, comme sa branche
>   `devel`, s'attachent encore par `NewSPDYExecutor` ;
> - le rôle des jobs accorde déjà `pods/attach: create`, que l'attache en
>   WebSocket exige.
>
> Les échecs d'octobre (`EOF for pod awx/automation-job-33-...`, puis
> `Failed to JSON parse a line from worker stream ... b''` côté AWX) ne se
> sont pas reproduits, et leur cause n'est pas connue. S'ils reviennent, lire
> le conteneur `awx-ee` du pod de tâches
> (`kubectl -n awx logs deploy/awx-task -c awx-ee`) avant de soupçonner le
> protocole. AWX reste épinglé.

## 21. Sources

- [Supported Java SE versions — WebSphere Liberty (MoRE)](https://www.ibm.com/docs/en/SSNGA9K/ae/lj_java_se.html)
- [Java SE 8 in WebSphere Application Server traditional V9](https://www.ibm.com/docs/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/covr_javase8.html)
- [What is new in WebSphere Application Server traditional](https://www.ibm.com/docs/en/SSEQTP_9.0.5/was/ae/welc_newinrelease.html)
- [IBM Java SDKs for WebSphere Liberty](https://www.ibm.com/support/pages/ibm-java-sdks-websphere-liberty)
- [WebSphere Liberty images on IBM Container Registry](https://github.com/WASdev/ci.docker/blob/main/docs/icr-images.md)
- [createWMQConnectionFactory command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmscf_create.html)
- [createWMQQueue command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmswmqq_create.html)
- [createWMQActivationSpec command](https://www.ibm.com/docs/SSAW57_9.0.0/com.ibm.websphere.nd.multiplatform.doc/ae/rmj_wmq_jmsas_create.html)
- [Configuring the timer service using scripting](https://ibm.com/support/knowledgecenter/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/txml_ejbTimer_config.html)
- [Configuring the runtime transaction service using scripting](https://www.ibm.com/support/knowledgecenter/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/txml_transaction.html)
- [Identifying and modifying the JPA specification level](https://www.ibm.com/docs/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/tejb_idmod_jpaspec.html)
- [Custom properties for improving application startup](https://www.ibm.com/support/pages/custom-properties-improving-application-startup-websphere-application-server)
- [SecurityConfigurationCommands command group for the AdminTask object](https://www.ibm.com/docs/en/SSEQTP_8.5.5/com.ibm.websphere.base.doc/ae/rxml_7securityconfig.html)
- [SSLConfigCommands command group for the AdminTask object (9.0.5)](https://www.ibm.com/support/knowledgecenter/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/rxml_atsslconfig.html)
- [SignerCertificateCommands command group (9.0.5)](https://www.ibm.com/docs/en/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/rxml_atsignercert.html)
- [Configuring HPEL with wsadmin scripting](https://www.ibm.com/docs/en/SSAW57_8.5.5/com.ibm.websphere.nd.multiplatform.doc/ae/ttrb_confHPELwsadmin.html)
- [Changing from basic mode to HPEL logging and tracing (9.0.5)](https://www.ibm.com/docs/en/SSAW57_9.0.5/com.ibm.websphere.nd.multiplatform.doc/ae/ttrb_compToHPEL.html)
- [Importing and exporting policy sets using wsadmin scripting](https://www.setgetweb.com/p/WAS9/ae/was6091.html)
- [Managing policy set attachments using wsadmin scripting](https://setgetweb.com/p/WAS9/ae/was6092.html)

Les relevés sur le dépôt source proviennent de l'inspection directe des sept archives de `github.com/CGA71/WAS`.
