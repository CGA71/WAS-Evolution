# Changelog

All notable changes to the `wasevo.websphere` collection.

The trajectory this collection implements is described in waves, in the
repository README sections 5 to 7. A wave is not a release: a release is
whatever is usable at the time.

## 0.1.0 — unreleased

Wave 0, the foundation. Nothing in production changes.

### Traditional plane

- `module_utils/wsadmin.py`: one `wsadmin` invocation per module call, a 0600
  properties file for the SOAP login, JSON back between sentinels. No secret
  ever reaches a command line.
- `plugins/jython/driver.py`: a single `wsadmin` entry point that dispatches to
  one handler and answers in JSON. Honours `check_mode` inside the session, so
  `--check` and `--diff` are real rather than advertised. Refuses a request a
  handler understood but cannot satisfy with the message alone, keeping the
  traceback for actual defects.
- `was_cluster`, with `handlers/cluster.py`: the pilot module. Reads, plans and
  writes in one session, and implements `state: absent`, which the body of work
  this replaces advertised on 34 resource types and implemented on 5.
- `was_cluster_member`, with `handlers/cluster_member.py`: the application
  servers of a cluster. Takes the whole member list in one call because a JVM
  start costs 30 to 60 seconds; handles the `-firstMember` rule itself;
  reconciles routing weight and pinned ports. Vertical and horizontal are the
  same call — see README section 18.
- `roles/traditional/server_member`: drives it, replayable on its own.
- `was_j2c_alias`, with `handlers/j2c_alias.py`, and `roles/traditional/j2c_alias`:
  cell-wide J2C authentication aliases, read from the shared model. The
  password cannot be compared, so `password_policy` says what to do about it -
  `on_create`, or `always` to rotate it; it never appears in a result, a diff
  or a log, and the stub tests search every answer to prove it.
- `playbooks/guard_target.yml`: the refusal of a run with no target, one
  definition imported by every playbook that acts on the deployment manager.
- `was_jdbc_provider` and `was_datasource`, with their handlers, and
  `roles/traditional/jdbc`: JDBC providers and datasources rendered from the
  same shared-model declaration the Liberty back-end renders. Cluster scope by
  default, another per datasource. Refuses a provider type the cell does not
  offer, a datasource whose J2C alias or provider does not exist, and a pool
  setting with no WAS equivalent. Replaces a classpath instead of appending to
  it, and compares only the settings a declaration names.
- `was_shared_library`, with its handler, and `roles/traditional/shared_library`:
  shared libraries from the shared model, in its two forms - a directory and a
  pattern, expanded on the deployment manager because WAS has no wildcard in a
  library class path, or an explicit list of jars. A pattern that matches
  nothing is refused. The Liberty template renders the explicit form too.
- `was_sibus`, with its handler, and `roles/traditional/sibus`: a service
  integration bus, its members and its destinations, in one wsadmin session
  per bus. Traditional only. A declared message store that differs from the
  engine's is reported as a warning and never changed, because changing it
  recreates the engine and discards its messages. Refuses a bus with no
  member and an exception destination that is not on the bus.
- `handlers/_scope.py`: scope resolution shared by every resource handler.
- `plugins/filter/traditional.py`: the traditional rendering of the shared
  model, as pure functions the stub tests call directly.

### Shared model, corrected

- `vendor` is now an abstract intent translated by
  `roles/model/vars/jdbc_vendors.yml`. It used to be pasted into the Liberty
  template, which produced `<properties.db2>` - not a Liberty element. The
  model refuses a vendor neither back-end can render.
- `roles/traditional/{prereqs_os,installation_manager,was_install,was_fixpack,was_sdk,profile_dmgr,profile_nodeagent,profile_standalone,config}`:
  the install and profile chain for the lab, each a separate job.
- `roles/traditional/{ihs,audit}`: declared, scheduled for wave 1, and failing
  with a message that says so rather than existing as an empty directory.

### Shared model

- `roles/model`: schema validation, the product × JDK matrix, the JVM intent
  translation table, and one mechanism for every WAS object name. A name is an
  input; the composed form is a fallback. README section 17.

### Liberty plane

- `roles/liberty/config_render`: `server.xml`, `jvm.options`, `server.env` from
  the shared model, with no cluster access at all — the GitOps boundary.
- `roles/liberty/{image_build,deploy,verify}`: declared, scheduled for waves 4
  and 5.

### Not yet implemented

The 33 remaining `wsadmin_*` resource types, `was_application` (there is not a
single `AdminApp.install` call in the body of work being replaced), the ~29
missing deletions, and AIX support in `prereqs_os`. See README section 5,
wave 1.
