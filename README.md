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
  typed Credentials, RIT -> RA -> RU -> PRD promotion, smoke tests.
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
9. Rebuild the RIT environment with the new tooling, feature-for-feature.
10. Render the pilot datasource, declared once, into the three trajectory couples.

**Entry criteria** — GitLab repository, AAP reachable, a RIT cell available for rebuild.

**Exit criteria** — RIT rebuilt end to end from AAP; `--check` and `--diff` demonstrated on a real change; the three renders of the pilot datasource agree.

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
6. Build the promotion workflow: `render -> build -> push -> [Approval] -> RIT -> smoke -> [Approval] -> RA -> ... -> PRD`.

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

# validate the model without touching anything
ansible-playbook playbooks/model_validate.yml

# render the pilot datasource in all three trajectory couples
ansible-playbook playbooks/pilot_render_matrix.yml

# validate one environment - the environment is a launch input, not a directory
ansible-playbook -i inventories/was $COL/model_validate.yml -e was_environment=RA

# traditional plane, dry run first - always
ansible-playbook -i inventories/was $COL/traditional_config.yml   -e was_environment=RIT --check --diff

# In AWX none of these flags are typed: the Survey asks for the environment,
# the channel and the production acknowledgement.
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
answer, `changed` and `diff`. All of that runs for real. Nine checks, including
two guards that fail the build if credentials ever reappear on a wsadmin command
line or the properties file is not `0600`, and one that asserts node
synchronisation fires on real changes only.

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

`sim:isolation` asserts the boundary rather than describing it: the CI identity
must **not** be able to exec into `kube-system`, `ci` or `default`, and both
NetworkPolicies must be in place. The ServiceAccount is bound by namespaced
Roles, never a ClusterRole, so a leaked CI token reaches exactly two throwaway
namespaces.

`sim:teardown` removes the pods and leaves the namespaces: they are
infrastructure applied once, and a pipeline that deletes them makes itself
unrunnable.

## 16. AWX

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

## 17. Sources

- [Supported Java SE versions — WebSphere Liberty (MoRE)](https://www.ibm.com/docs/en/SSNGA9K/ae/lj_java_se.html)
- [Java SE 8 in WebSphere Application Server traditional V9](https://www.ibm.com/docs/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/covr_javase8.html)
- [What is new in WebSphere Application Server traditional](https://www.ibm.com/docs/en/SSEQTP_9.0.5/was/ae/welc_newinrelease.html)
- [IBM Java SDKs for WebSphere Liberty](https://www.ibm.com/support/pages/ibm-java-sdks-websphere-liberty)
- [WebSphere Liberty images on IBM Container Registry](https://github.com/WASdev/ci.docker/blob/main/docs/icr-images.md)

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
  Credentials types, promotion RIT -> RA -> RU -> PRD, tests de fumee.
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
9. Reconstruire l'environnement RIT avec le nouvel outillage, à iso-fonctionnalité.
10. Rendre le datasource pilote, déclaré une seule fois, dans les trois couples de la trajectoire.

**Critères d'entrée** — dépôt GitLab, AAP joignable, une cellule RIT disponible pour reconstruction.

**Critères de sortie** — RIT reconstruit de bout en bout depuis AAP ; `--check` et `--diff` démontrés sur un changement réel ; les trois rendus du datasource pilote concordent.

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
6. Construire le workflow de promotion : `render -> build -> push -> [Approval] -> RIT -> smoke -> [Approval] -> RA -> ... -> PRD`.

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

# valider le modele sans rien toucher
ansible-playbook playbooks/model_validate.yml

# rendre le datasource pilote dans les trois couples de la trajectoire
ansible-playbook playbooks/pilot_render_matrix.yml

# plan traditionnel, a blanc d'abord
ansible-playbook -i inventories/was $COL/traditional_config.yml -e was_environment=RIT --check --diff
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
JSON, `changed` et `diff`. Tout cela tourne réellement. Neuf contrôles, dont
deux garde-fous qui cassent le build si des identifiants réapparaissent sur une
ligne de commande wsadmin ou si le fichier de propriétés n'est pas en `0600`,
et un qui vérifie que la synchronisation des nœuds ne part que sur un vrai
changement.

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

`sim:isolation` vérifie la frontière plutôt que de la décrire : l'identité CI ne
doit **pas** pouvoir faire d'exec dans `kube-system`, `ci` ou `default`, et les
deux NetworkPolicies doivent être en place. Le ServiceAccount est lié par des
Roles namespacés, jamais par un ClusterRole, donc un token CI fuité n'atteint
exactement que deux namespaces jetables.

`sim:teardown` supprime les pods et laisse les namespaces : ce sont des
ressources d'infrastructure appliquées une fois, et une chaîne qui les supprime
se rend elle-même inexécutable.

## 16. AWX

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

## 17. Sources

- [Supported Java SE versions — WebSphere Liberty (MoRE)](https://www.ibm.com/docs/en/SSNGA9K/ae/lj_java_se.html)
- [Java SE 8 in WebSphere Application Server traditional V9](https://www.ibm.com/docs/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/covr_javase8.html)
- [What is new in WebSphere Application Server traditional](https://www.ibm.com/docs/en/SSEQTP_9.0.5/was/ae/welc_newinrelease.html)
- [IBM Java SDKs for WebSphere Liberty](https://www.ibm.com/support/pages/ibm-java-sdks-websphere-liberty)
- [WebSphere Liberty images on IBM Container Registry](https://github.com/WASdev/ci.docker/blob/main/docs/icr-images.md)

Les relevés sur le dépôt source proviennent de l'inspection directe des sept archives de `github.com/CGA71/WAS`.
