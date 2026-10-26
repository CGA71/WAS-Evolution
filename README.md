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

# validate the model without touching anything
ansible-playbook playbooks/model_validate.yml

# render the pilot datasource in all three trajectory couples
ansible-playbook playbooks/pilot_render_matrix.yml

# validate one environment - the environment is a launch input, not a directory
ansible-playbook -i inventories/was $COL/model_validate.yml -e was_environment=RA

# traditional plane, dry run first - always
ansible-playbook -i inventories/was $COL/traditional_config.yml   -e was_environment=<code> --check --diff

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

### The build goes through AWX, as a workflow

Nothing is installed or named by hand on a target. The construction is a
workflow of job templates, and the survey is where the names and the
environment enter:

| Node | Job template | Playbook |
|---|---|---|
| 0 | Forge preflight | `forge_preflight.yml` |
| 1 | Install IBM Installation Manager | `lab_install_im.yml` |
| 2 | Apply fixpacks, pass 1 | `lab_apply_fixpacks.yml` |
| 3 | Install WAS and the SDK | `lab_install_was.yml` |
| 4 | Apply fixpacks, pass 2 | `lab_apply_fixpacks.yml` |
| 5 | Create the profiles | the `profile_dmgr` / `profile_nodeagent` roles |
| 6 | Create the cluster and its members | `traditional_config.yml` |

The survey asks for the target environment, the channel, the production
acknowledgement, and any object name the site wants to set rather than derive.
None of those are flags anybody types: a workflow node carries them, and the
promotion from one environment to the next is the same workflow with a
different answer.

Two things follow from this and are worth stating plainly. The environment code
is **not** a property of a machine — the same host can be built as any
environment, which is why no inventory declares one. And the install jobs are
name-neutral: `imcl` receives the offering, the repository and the installation
directory, nothing derived from the environment or the channel. The names are
consumed by the profile and configuration jobs, which is where a wrong answer
shows up and where it is cheap to correct.

## 18. AWX

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

## 19. Sources

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

# valider le modele sans rien toucher
ansible-playbook playbooks/model_validate.yml

# rendre le datasource pilote dans les trois couples de la trajectoire
ansible-playbook playbooks/pilot_render_matrix.yml

# plan traditionnel, a blanc d'abord
ansible-playbook -i inventories/was $COL/traditional_config.yml -e was_environment=<code> --check --diff
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

### La construction passe par AWX, en workflow

Rien n'est installé ni nommé à la main sur une cible. La construction est un
workflow de job templates, et le survey est l'endroit par lequel les noms et
l'environnement entrent :

| Nœud | Job template | Playbook |
|---|---|---|
| 0 | Préflight de la forge | `forge_preflight.yml` |
| 1 | Installer IBM Installation Manager | `lab_install_im.yml` |
| 2 | Appliquer les fixpacks, passe 1 | `lab_apply_fixpacks.yml` |
| 3 | Installer WAS et le SDK | `lab_install_was.yml` |
| 4 | Appliquer les fixpacks, passe 2 | `lab_apply_fixpacks.yml` |
| 5 | Créer les profils | rôles `profile_dmgr` / `profile_nodeagent` |
| 6 | Créer le cluster et ses membres | `traditional_config.yml` |

Le survey demande l'environnement cible, le canal, l'acquittement de
production, et tout nom d'objet que le site veut fixer plutôt que dériver.
Aucun de ces éléments n'est un drapeau que quelqu'un tape : un nœud de workflow
les porte, et la promotion d'un environnement au suivant est le même workflow
avec une réponse différente.

Deux conséquences méritent d'être dites franchement. Le code d'environnement
n'est **pas** une propriété d'une machine — le même hôte peut être construit
comme n'importe quel environnement, et c'est pourquoi aucun inventaire n'en
déclare. Et les jobs d'installation sont neutres vis-à-vis des noms : `imcl`
reçoit l'offre, le dépôt et le répertoire d'installation, rien qui dérive de
l'environnement ou du canal. Les noms sont consommés par les jobs de profil et
de configuration, là où une mauvaise réponse se voit et où elle coûte peu à
corriger.

## 18. AWX

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

## 19. Sources

- [Supported Java SE versions — WebSphere Liberty (MoRE)](https://www.ibm.com/docs/en/SSNGA9K/ae/lj_java_se.html)
- [Java SE 8 in WebSphere Application Server traditional V9](https://www.ibm.com/docs/en/SSEQTP_9.0.5/com.ibm.websphere.base.doc/ae/covr_javase8.html)
- [What is new in WebSphere Application Server traditional](https://www.ibm.com/docs/en/SSEQTP_9.0.5/was/ae/welc_newinrelease.html)
- [IBM Java SDKs for WebSphere Liberty](https://www.ibm.com/support/pages/ibm-java-sdks-websphere-liberty)
- [WebSphere Liberty images on IBM Container Registry](https://github.com/WASdev/ci.docker/blob/main/docs/icr-images.md)

Les relevés sur le dépôt source proviennent de l'inspection directe des sept archives de `github.com/CGA71/WAS`.
