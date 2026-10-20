# wasevo.websphere

Ansible collection for IBM WebSphere Application Server ND (traditional) and
WebSphere Liberty, covering the three-phase trajectory to OpenShift.

The full architecture, the phase-by-phase action lists and the product x JDK
matrix are in the repository root `README.md`, in English and French.

## Planes

| Plane | Mechanism | Why |
|---|---|---|
| `plugins/modules/` + `plugins/jython/` | modules driving one wsadmin session | wsadmin is imperative; idempotency, `--check` and `--diff` have to be built |
| `roles/liberty/` | `kubernetes.core` + the Liberty operator CRD | Kubernetes already reconciles; modules here would duplicate `kubernetes.core` |
| `roles/model/` | schema validation + JVM intent translation | The one place that knows both worlds, and the only source of truth |

## Hard rules

- **Never merge `liberty/config_render` and `liberty/deploy`.** `config_render`
  has no cluster access; it is the GitOps boundary.
- **Never put a secret on a command line.** `module_utils/wsadmin.py` writes a
  0600 properties file and removes it; `no_log` covers the module argument.
- **Never write a raw JVM flag into the model.** Declare an intent and let
  `roles/model/vars/jvm_flags.yml` render it, or it will not survive a VM
  change or the move into a container.
