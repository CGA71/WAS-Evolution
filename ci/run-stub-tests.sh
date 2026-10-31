#!/usr/bin/env bash
# Exercise the traditional-plane chain with no cluster and no Ansible.
#
# This runs the real driver.py and the real cluster handler against the fake
# cell. It is the cheapest gate in the pipeline and it catches most regressions
# before anything is deployed: dispatch, payload parsing, the read/plan/write
# split, JSON encoding, sentinel framing, and whether changed is honest.
#
# What it does NOT prove: that the wsadmin calls in the handlers are correct
# WAS API usage. Only a real cell proves that.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTION="$ROOT/ansible_collections/wasevo/websphere"
STUB="$COLLECTION/roles/traditional/config/files/wsadmin-stub"
DRIVER="$COLLECTION/plugins/jython/driver.py"
HANDLERS="$COLLECTION/plugins/jython/handlers"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export WAS_SIM_STATE="$WORK/state.json"
export PYTHONPATH="$STUB:$HANDLERS"

PY="${PYTHON:-python3}"
fail=0

payload() {
    cat > "$WORK/$1.json"
}

payload present <<'JSON'
{"resource":"cluster","state":"present",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB","prefer_local":"true"},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload drift_check <<'JSON'
{"resource":"cluster","state":"present",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB","prefer_local":"false"},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload absent <<'JSON'
{"resource":"cluster","state":"absent",
 "params":{"name":"ClusterEXT","cell_name":"Extranet_STUB"},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# --------------------------------------------------------------------------
# Cluster members: the application servers
# --------------------------------------------------------------------------
# One call carries the whole member list, because a wsadmin JVM start costs 30
# to 60 seconds. This payload is a VERTICAL and HORIZONTAL cluster at once -
# two members on STUBNode01, one on STUBNode02 - which is the shape an estate
# actually has, and the shape that catches the -firstMember rule: the fake cell
# refuses the call if the handler sends -firstMember for anything but the first
# member of the cluster.
payload members <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "template_name":"default",
           "members":[{"node":"STUBNode01","name":"ClusterEXT_STUBNode01_01","weight":2,"gen_unique_ports":true},
                      {"node":"STUBNode01","name":"ClusterEXT_STUBNode01_02","weight":2,"gen_unique_ports":true},
                      {"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01","weight":2,"gen_unique_ports":true}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A pinned port. Only the endpoints named here are read back, so this also
# exercises the serverindex read path that a member with no pinned port skips.
payload member_pin <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"ClusterEXT_STUBNode01_02",
                       "ports":{"WC_defaulthost":9382}}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Weight 0 drains a member without deleting it.
payload member_drain <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01","weight":0}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload member_new_check <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode03","name":"ClusterEXT_STUBNode03_01"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload member_absent <<'JSON'
{"resource":"cluster_member","state":"absent",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode02","name":"ClusterEXT_STUBNode02_01"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Members asked for in a cell that has no such cluster. A refusal, not a crash:
# the handler raises ValueError, the driver reports the sentence alone.
payload member_no_cluster <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterNOPE","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"whatever"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A check run on a cell that has no such cluster. NOT a refusal: under --check
# the cluster is a future, created by the step before this one in the same run,
# and a dry run of a first build is the run most worth rehearsing.
payload member_future_check <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterNOTYET","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode01","name":"ClusterNOTYET_STUBNode01_01"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

# Two members on ONE node with genUniquePorts off. They both copy the
# template's ports, which is a collision - and the reason the module defaults
# it to true. WAS saves this configuration happily and the second server fails
# to start hours later; the fake cell refuses it at creation.
payload member_port_clash <<'JSON'
{"resource":"cluster_member","state":"present",
 "params":{"cluster_name":"ClusterEXT","cell_name":"Extranet_STUB",
           "members":[{"node":"STUBNode09","name":"Clash01","gen_unique_ports":false},
                      {"node":"STUBNode09","name":"Clash02","gen_unique_ports":false}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# --------------------------------------------------------------------------
# J2C authentication aliases
# --------------------------------------------------------------------------
# The password used here is a marker, searched for in every driver answer
# below: it must never come back out. The real AdminConfig returns a stored
# password encoded, so a handler that read it back would work in this fake and
# leak or break on a real cell - the fake refuses to serve it at all.
payload j2c_create <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-1","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload j2c_user_check <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app2","password":"MARKER-pw-1","description":"stub db"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

# A new password under on_create: nothing to compare, so nothing written.
payload j2c_new_pw_on_create <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-2","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# The same under always: the rotation.
payload j2c_rotate <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"always",
           "aliases":[{"name":"stubDbAlias","user":"app","password":"MARKER-pw-2","description":"stub db"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload j2c_absent <<'JSON'
{"resource":"j2c_alias","state":"absent",
 "params":{"aliases":[{"name":"stubDbAlias","user":"app"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# --------------------------------------------------------------------------
# JDBC providers and datasources, at the cluster's scope
# --------------------------------------------------------------------------
# Arguments as the role renders them from the shared model - the vendor table
# already applied, the pool already in WAS attributes and seconds.
payload jdbc_prov_unknown <<'JSON'
{"resource":"jdbc_provider","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "providers":[{"name":"stubProv","database_type":"DB2","provider_type":"DB2 For Mainframes On Mars",
                         "implementation_type":"Connection pool data source","classpath":"/drv/jt400.jar","native_path":"","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload jdbc_prov <<'JSON'
{"resource":"jdbc_provider","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "providers":[{"name":"stubProv","database_type":"DB2","provider_type":"DB2 UDB for iSeries (Toolbox)",
                         "implementation_type":"Connection pool data source","classpath":"/drv/jt400.jar","native_path":"","description":"stub"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A new driver jar. modify on a list attribute APPENDS in WAS, so a handler
# that did not unset first would leave the old jar ahead of the new one.
payload jdbc_prov_newjar <<'JSON'
{"resource":"jdbc_provider","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "providers":[{"name":"stubProv","database_type":"DB2","provider_type":"DB2 UDB for iSeries (Toolbox)",
                         "implementation_type":"Connection pool data source","classpath":"/drv/jt400-11.jar","native_path":"","description":"stub"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload jdbc_prov_absent <<'JSON'
{"resource":"jdbc_provider","state":"absent",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "providers":[{"name":"stubProv","database_type":"DB2","provider_type":"DB2 UDB for iSeries (Toolbox)",
                         "implementation_type":"Connection pool data source"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds_alias <<'JSON'
{"resource":"j2c_alias","state":"present",
 "params":{"password_policy":"on_create",
           "aliases":[{"name":"stubDsAlias","user":"app","password":"MARKER-pw-3","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds_alias_absent <<'JSON'
{"resource":"j2c_alias","state":"absent",
 "params":{"aliases":[{"name":"stubDsAlias","user":"app"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds <<'JSON'
{"resource":"datasource","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "datasources":[{"name":"stubDs","provider":"stubProv","jndi_name":"jdbc/stub",
                           "helper":"com.ibm.websphere.rsadapter.DB2AS400DataStoreHelper","auth_alias":"stubDsAlias",
                           "statement_cache_size":20,
                           "properties":{"databaseName":"STUB","serverName":"as400.stub"},
                           "pool":{"maxConnections":30,"minConnections":5,"connectionTimeout":30,"unusedTimeout":1800}}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds_pool <<'JSON'
{"resource":"datasource","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "datasources":[{"name":"stubDs","provider":"stubProv","jndi_name":"jdbc/stub",
                           "helper":"com.ibm.websphere.rsadapter.DB2AS400DataStoreHelper","auth_alias":"stubDsAlias",
                           "statement_cache_size":20,
                           "properties":{"databaseName":"STUB","serverName":"as400.stub"},
                           "pool":{"maxConnections":50,"minConnections":5,"connectionTimeout":30,"unusedTimeout":1800}}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds_check_new <<'JSON'
{"resource":"datasource","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "datasources":[{"name":"stubDs2","provider":"stubProv","jndi_name":"jdbc/stub2",
                           "helper":"com.ibm.websphere.rsadapter.DB2AS400DataStoreHelper","auth_alias":"stubDsAlias"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload lib <<'JSON'
{"resource":"shared_library","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "libraries":[{"name":"stubLib","class_path":["/s/a.jar","/s/b.jar"],"native_path":[],
                         "description":"stub","isolated":false}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A jar dropped into the library directory: the role expands the pattern again
# and hands over one more entry. Unset-then-write, as for a JDBC classpath.
payload lib_more <<'JSON'
{"resource":"shared_library","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "libraries":[{"name":"stubLib","class_path":["/s/a.jar","/s/b.jar","/s/c.jar"],"native_path":[],
                         "description":"stub","isolated":false}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload lib_absent <<'JSON'
{"resource":"shared_library","state":"absent",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "libraries":[{"name":"stubLib","class_path":[]}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload sib <<'JSON'
{"resource":"sibus","state":"present",
 "params":{"bus":"StubBus","description":"stub","security":false,
           "members":[{"cluster":"ClusterEXT","store":"file","policy":"HA"}],
           "destinations":[{"name":"StubQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"StubDLQ","description":""},
                           {"name":"StubDLQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""},
                           {"name":"StubT","type":"topic_space","reliability":"RELIABLE_NONPERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload sib_redelivery <<'JSON'
{"resource":"sibus","state":"present",
 "params":{"bus":"StubBus","description":"stub","security":false,
           "members":[{"cluster":"ClusterEXT","store":"file","policy":"HA"}],
           "destinations":[{"name":"StubQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":10,
                            "exception_destination":"StubDLQ","description":""},
                           {"name":"StubDLQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""},
                           {"name":"StubT","type":"topic_space","reliability":"RELIABLE_NONPERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# The member declared with a data store while its engine has a file store.
# Changing it recreates the engine and discards its messages, so the run must
# report it and change nothing.
payload sib_store_drift <<'JSON'
{"resource":"sibus","state":"present",
 "params":{"bus":"StubBus","description":"stub","security":false,
           "members":[{"cluster":"ClusterEXT","store":"data","policy":"HA"}],
           "destinations":[{"name":"StubQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":10,
                            "exception_destination":"StubDLQ","description":""},
                           {"name":"StubDLQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""},
                           {"name":"StubT","type":"topic_space","reliability":"RELIABLE_NONPERSISTENT","max_failed_deliveries":5,
                            "exception_destination":"","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload sib_bad_exception <<'JSON'
{"resource":"sibus","state":"present",
 "params":{"bus":"StubBus","description":"stub","security":false,
           "members":[{"cluster":"ClusterEXT","store":"file","policy":"HA"}],
           "destinations":[{"name":"StubQ","type":"queue","reliability":"ASSURED_PERSISTENT","max_failed_deliveries":10,
                            "exception_destination":"Nowhere","description":""}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# JMS on StubBus, while it exists: the four kinds a message-driven bean needs.
payload jms <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib","known_destinations":{},
           "connection_factories":[{"name":"StubCF","jndi_name":"jms/stubCF","bus":"StubBus"}],
           "queues":[{"name":"StubJmsQ","jndi_name":"jms/stubQ","queue":"StubQ","bus":"StubBus"}],
           "topics":[{"name":"StubJmsT","jndi_name":"jms/stubT","topic_space":"StubT","topic_name":"eur","bus":"StubBus"}],
           "activation_specs":[{"name":"StubAS","jndi_name":"jms/stubAS","destination_jndi":"jms/stubQ","bus":"StubBus"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload jms_cf_change <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib","known_destinations":{},
           "connection_factories":[{"name":"StubCF","jndi_name":"jms/stubCF","bus":"StubBus","description":"orders"}],
           "queues":[{"name":"StubJmsQ","jndi_name":"jms/stubQ","queue":"StubQ","bus":"StubBus"}],
           "topics":[{"name":"StubJmsT","jndi_name":"jms/stubT","topic_space":"StubT","topic_name":"eur","bus":"StubBus"}],
           "activation_specs":[{"name":"StubAS","jndi_name":"jms/stubAS","destination_jndi":"jms/stubQ","bus":"StubBus"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# A JMS queue on a topic space: WAS saves it, the first send fails.
payload jms_queue_on_topic <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib","known_destinations":{},
           "queues":[{"name":"WrongQ","jndi_name":"jms/wrongQ","queue":"StubT","bus":"StubBus"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# An activation spec on a JNDI nothing carries: the bean deploys and starves.
payload jms_as_unknown <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib","known_destinations":{},
           "activation_specs":[{"name":"LostAS","jndi_name":"jms/lostAS","destination_jndi":"jms/nowhere","bus":"StubBus"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# The same activation spec, its queue declared at ANOTHER scope: WAS resolves
# JNDI names through the scopes, so this is valid and must not be refused.
payload jms_as_other_scope <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib",
           "known_destinations":{"jms/cellQueue":"javax.jms.Queue"},
           "activation_specs":[{"name":"CellAS","jndi_name":"jms/cellAS","destination_jndi":"jms/cellQueue","bus":"StubBus"}]},
 "check_mode":true,"save_config":true,"sync_nodes":true}
JSON

payload jms_absent <<'JSON'
{"resource":"jms","state":"absent",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"sib","known_destinations":{},
           "connection_factories":[{"name":"StubCF","jndi_name":"jms/stubCF"}],
           "queues":[{"name":"StubJmsQ","jndi_name":"jms/stubQ"}],
           "topics":[{"name":"StubJmsT","jndi_name":"jms/stubT"}],
           "activation_specs":[{"name":"StubAS","jndi_name":"jms/stubAS","destination_jndi":"jms/stubQ"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# JMS on IBM MQ, at the same scope: the queue manager declared on the factory
# and the spec, its port and channel left to WAS - which fills them in and
# shows them, and a replay must not read that as a change.
payload mq <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"mq","known_destinations":{},
           "connection_factories":[{"name":"PayCF","jndi_name":"jms/payCF","qmgr":"QM1","type":"QCF"}],
           "queues":[{"name":"PayQ","jndi_name":"jms/payQ","queue":"PAYMENTS.IN"}],
           "topics":[{"name":"RatesT","jndi_name":"jms/ratesT","topic_name":"rates/eur"}],
           "activation_specs":[{"name":"PayAS","jndi_name":"jms/payAS","destination_jndi":"jms/payQ","qmgr":"QM1"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload mq_client <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"mq","known_destinations":{},
           "connection_factories":[{"name":"PayCF","jndi_name":"jms/payCF","qmgr":"QM1","type":"QCF",
                                    "transport":"CLIENT","host":"mq.sim","port":1415,"channel":"APP.SVRCONN"}],
           "queues":[{"name":"PayQ","jndi_name":"jms/payQ","queue":"PAYMENTS.IN"}],
           "topics":[{"name":"RatesT","jndi_name":"jms/ratesT","topic_name":"rates/eur"}],
           "activation_specs":[{"name":"PayAS","jndi_name":"jms/payAS","destination_jndi":"jms/payQ","qmgr":"QM1"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# CLIENT with nowhere to go: WAS saves it, the first connection fails.
payload mq_client_nowhere <<'JSON'
{"resource":"jms","state":"present",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"mq","known_destinations":{},
           "connection_factories":[{"name":"LostCF","jndi_name":"jms/lostCF","qmgr":"QM1","transport":"CLIENT"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload mq_absent <<'JSON'
{"resource":"jms","state":"absent",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},"provider":"mq","known_destinations":{},
           "connection_factories":[{"name":"PayCF","jndi_name":"jms/payCF"}],
           "queues":[{"name":"PayQ","jndi_name":"jms/payQ"}],
           "topics":[{"name":"RatesT","jndi_name":"jms/ratesT"}],
           "activation_specs":[{"name":"PayAS","jndi_name":"jms/payAS","destination_jndi":"jms/payQ"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload sib_absent <<'JSON'
{"resource":"sibus","state":"absent",
 "params":{"bus":"StubBus","members":[],"destinations":[]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

payload ds_absent <<'JSON'
{"resource":"datasource","state":"absent",
 "params":{"scope":{"type":"cluster","cluster":"ClusterEXT"},
           "datasources":[{"name":"stubDs","provider":"stubProv","jndi_name":"jdbc/stub","helper":"x"}]},
 "check_mode":false,"save_config":true,"sync_nodes":true}
JSON

# Run one payload through the driver and print the resulting `changed`, or an
# error. Deliberately goes through the sentinel extraction the module uses, so
# a change to the framing breaks here too.
#
# The raw output of every run is appended to $WORK/<payload>.raw, so a check
# that inspects what the driver said - the password-leak guard - reads the
# answers of the runs that actually happened, all of them, instead of running
# the payload again, which would write twice and skew every count after it.
run_one() {
    "$PY" "$STUB/shim.py" "$DRIVER" "$WORK/$1.json" 2>&1 \
      | tee -a "$WORK/$1.raw" \
      | sed -n '/<<<VSSP-JSON>>>/,/<<<END-VSSP-JSON>>>/p' \
      | sed '1d;$d' \
      | "$PY" -c '
import json, sys
answer = json.load(sys.stdin)
if answer.get("failed"):
    print("ERROR " + (answer.get("msg") or "")[:400])
else:
    print(str(answer.get("changed")).lower())
'
}

expect() {
    local label="$1" pl="$2" want="$3"
    local got
    got="$(run_one "$pl")"
    if [ "$got" = "$want" ]; then
        printf '  ok     %-48s changed=%s\n' "$label" "$got"
    else
        printf '  FAIL   %-48s expected %s, got: %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

# The whole message, for the checks that are about what a refusal SAYS.
# A refusal an operator cannot act on is a crash with better manners.
msg_of() {
    "$PY" "$STUB/shim.py" "$DRIVER" "$WORK/$1.json" 2>&1 \
      | sed -n '/<<<VSSP-JSON>>>/,/<<<END-VSSP-JSON>>>/p' \
      | sed '1d;$d' \
      | "$PY" -c '
import json, sys
print((json.load(sys.stdin).get("msg") or "").replace("\n", " "))
'
}

expect_refusal() {
    local label="$1" pl="$2" needle="$3"
    local got
    got="$(msg_of "$pl")"
    case "$got" in
        *"$needle"*)
            printf '  ok     %-48s refused, and says why\n' "$label" ;;
        *)
            printf '  FAIL   %-48s expected a refusal naming "%s", got: %s\n' \
                "$label" "$needle" "${got:-<no message>}"
            fail=1 ;;
    esac
}

# How many members the fake cell holds, and the port of one of them. Asserted
# rather than described: "check mode writes nothing" is only worth claiming if
# something looks.
cell_members() {
    "$PY" -c '
import json, os
state = json.load(open(os.environ["WAS_SIM_STATE"]))
print(len(state.get("members", {})))
'
}

member_port() {
    "$PY" -c '
import json, os, sys
state = json.load(open(os.environ["WAS_SIM_STATE"]))
server, endpoint = sys.argv[1], sys.argv[2]
for entry in state.get("entries", {}).values():
    if entry["serverName"] != server:
        continue
    for special_id in entry["special_ids"]:
        special = state["specials"][special_id]
        if special["endPointName"] == endpoint:
            print(state["ports"][special["endPoint"]]["port"])
            sys.exit(0)
print("absent")
' "$1" "$2"
}

expect_value() {
    local label="$1" got="$2" want="$3"
    if [ "$got" = "$want" ]; then
        printf '  ok     %-48s %s\n' "$label" "$got"
    else
        printf '  FAIL   %-48s expected %s, got %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

echo "=== module -> driver -> handler -> fake cell ==="
expect "create"                             present     true
expect "replay (idempotency)"               present     false
expect "--check on a real gap"              drift_check true
expect "replay after --check (nothing written)" present false

echo
echo "=== cluster members: the application servers ==="
# Vertical and horizontal in one call: 2 JVMs on STUBNode01, 1 on STUBNode02.
expect "create 3 members in one wsadmin call"  members          true
expect "replay (idempotency)"                  members          false
expect_value "members in the cell" "$(cell_members)" "3"
expect_value "vertical members got distinct ports" \
    "$([ "$(member_port ClusterEXT_STUBNode01_01 WC_defaulthost)" \
       != "$(member_port ClusterEXT_STUBNode01_02 WC_defaulthost)" ] && echo distinct)" \
    "distinct"

expect "pin an endpoint port"                  member_pin       true
expect_value "the pinned port was applied" \
    "$(member_port ClusterEXT_STUBNode01_02 WC_defaulthost)" "9382"
# The regression this guards: planning a port change used to mutate the state
# it was comparing against - a shallow dict copy - so the write was skipped and
# the diff claimed a change that never happened. Convergence is the proof.
expect "replay the pinned port (convergence)"  member_pin       false

expect "drain a member with weight 0"          member_drain     true
expect "replay the drain"                      member_drain     false

expect "--check a new member"                  member_new_check true
expect_value "check mode created nothing" "$(cell_members)" "3"

expect "delete one member"                     member_absent    true
expect "replay the delete"                     member_absent    false
expect_value "members left in the cell" "$(cell_members)" "2"

expect_refusal "members in a cluster that does not exist" \
    member_no_cluster "does not exist in this cell"
# The same request under --check is a plan, not a refusal: the cluster is a
# future, and a dry run of a first build has to be possible.
expect "--check on a cluster not created yet"   member_future_check true
expect_value "and it still created nothing" "$(cell_members)" "2"
expect_refusal "two JVMs on one node claiming one port" \
    member_port_clash "cannot share a port"

echo
echo "=== J2C authentication aliases ==="
# The stored password, and how many times it was written - read from the fake
# cell's state, which is the only place it exists.
j2c_pw() {
    "$PY" -c '
import json, os, sys
for o in json.load(open(os.environ["WAS_SIM_STATE"])).get("objects", {}).values():
    if o["type"] == "JAASAuthData" and o["attrs"]["alias"] == sys.argv[1]:
        print("%s/%s" % (o["attrs"]["_password"], o["attrs"]["_password_writes"]))
        sys.exit(0)
print("absent")
' "$1"
}

expect "create an alias"                        j2c_create           true
expect "replay (idempotency)"                   j2c_create           false
expect "--check a new user"                     j2c_user_check       true
expect_value "the check wrote nothing" "$(j2c_pw stubDbAlias)" "MARKER-pw-1/1"
expect "new password, on_create: left alone"    j2c_new_pw_on_create false
expect_value "and it was not written" "$(j2c_pw stubDbAlias)" "MARKER-pw-1/1"
expect "new password, always: rotated"          j2c_rotate           true
expect_value "and it was written once more" "$(j2c_pw stubDbAlias)" "MARKER-pw-2/2"

# The guard that matters most for this resource. Every answer the driver gave
# about an alias is searched for the password markers - including the rotation,
# where the new password was in the request and must not be in the answer.
leak=""
for pl in j2c_create j2c_user_check j2c_new_pw_on_create j2c_rotate; do
    if grep -q "MARKER-pw" "$WORK/$pl.raw"; then
        leak="$leak $pl"
    fi
done
expect_value "no password in any driver answer" "${leak:-none}" "none"

expect "delete"                                 j2c_absent           true
expect "replay delete"                          j2c_absent           false

echo
echo "=== JDBC providers and datasources ==="
# Read a value back from the fake cell: a provider's classpath, a datasource's
# pool attribute or custom property, how many datasources exist.
cell_value() {
    "$PY" -c '
import json, os, sys
objs = json.load(open(os.environ["WAS_SIM_STATE"])).get("objects", {})
kind, name, key = sys.argv[1], sys.argv[2], sys.argv[3]
def find(t, n):
    for i, o in objs.items():
        if o["type"] == t and o["attrs"].get("name") == n:
            return i, o
    return None, None
if kind == "count":
    print(sum(1 for o in objs.values() if o["type"] == name)); sys.exit(0)
if kind == "provider":
    _, o = find("JDBCProvider", name); print(o["attrs"][key] if o else "absent"); sys.exit(0)
if kind == "library":
    _, o = find("Library", name); print(o["attrs"].get(key, "") if o else "absent"); sys.exit(0)
_, ds = find("DataSource", name)
if ds is None:
    print("absent"); sys.exit(0)
if kind == "pool":
    print(objs[ds["attrs"]["connectionPool"]]["attrs"][key]); sys.exit(0)
if kind == "property":
    for p in objs[ds["attrs"]["propertySet"]]["attrs"]["resourceProperties"]:
        if objs[p]["attrs"]["name"] == key:
            print(objs[p]["attrs"]["value"]); sys.exit(0)
    print("absent")
' "$1" "$2" "$3"
}

expect_refusal "a provider type the cell does not offer" \
    jdbc_prov_unknown "is not offered by this cell"
expect "create a provider"                      jdbc_prov            true
expect "replay (idempotency)"                   jdbc_prov            false
expect "a new driver jar"                       jdbc_prov_newjar     true
expect_value "the jar was replaced, not appended" \
    "$(cell_value provider stubProv classpath)" "/drv/jt400-11.jar"

expect_refusal "a datasource whose J2C alias does not exist" \
    ds "does not exist in the cell"
expect "the alias it needs"                     ds_alias             true
expect "create a datasource"                    ds                   true
expect "replay (idempotency)"                   ds                   false
expect_value "pool maxConnections set"      "$(cell_value pool stubDs maxConnections)" "30"
expect_value "pool reapTime left at default" "$(cell_value pool stubDs reapTime)" "180"
expect_value "custom property set"          "$(cell_value property stubDs databaseName)" "STUB"
expect "pool maxConnections 30 -> 50"           ds_pool              true
expect "replay (idempotency)"                   ds_pool              false
expect "--check a new datasource"               ds_check_new         true
expect_value "the check created nothing" "$(cell_value count DataSource -)" "1"
expect "delete the datasource"                  ds_absent            true
expect "replay the delete"                      ds_absent            false
expect "delete the provider"                    jdbc_prov_absent     true
expect "replay the delete"                      jdbc_prov_absent     false
expect "delete the alias"                       ds_alias_absent      true

echo
echo "=== shared libraries ==="
expect "create a library"                       lib                  true
expect "replay (idempotency)"                   lib                  false
expect "a jar added to its directory"           lib_more             true
expect_value "the class path was replaced, not appended" \
    "$(cell_value library stubLib classPath)" "/s/a.jar;/s/b.jar;/s/c.jar"
expect "replay (idempotency)"                   lib_more             false
expect "delete"                                 lib_absent           true
expect "replay delete"                          lib_absent           false

echo
echo "=== service integration bus ==="
engine_store() {
    "$PY" -c '
import json, os
for o in json.load(open(os.environ["WAS_SIM_STATE"])).get("objects", {}).values():
    if o["type"] == "SIBMessagingEngine":
        print("data" if o["attrs"]["dataStore"] else "file")
' | head -1
}
expect "create bus, member and destinations"    sib                  true
expect "replay (idempotency)"                   sib                  false
expect_value "three destinations" "$(cell_value count SIBQueue -)/$(cell_value count SIBTopicSpace -)" "2/1"
expect "redelivery limit 5 -> 10"               sib_redelivery       true
expect "replay (idempotency)"                   sib_redelivery       false
# The safety property of this resource: a store change is reported, never done.
expect "declared store data, engine has file"   sib_store_drift      false
expect_value "the engine was not recreated" "$(engine_store)" "file"
expect_refusal "an exception destination that is not on the bus" \
    sib_bad_exception "is not a destination of bus"

echo
echo "=== JMS on the default messaging provider ==="
expect "create factory, queue, topic, spec"     jms                  true
expect "replay (idempotency)"                   jms                  false
expect_value "four JMS resources" \
    "$(cell_value count SIBJMSConnectionFactory -)$(cell_value count SIBJMSQueue -)$(cell_value count SIBJMSTopic -)$(cell_value count SIBJMSActivationSpec -)" "1111"
expect "connection factory description"         jms_cf_change        true
expect "replay (idempotency)"                   jms_cf_change        false
expect_refusal "a JMS queue on a topic space" \
    jms_queue_on_topic "which is a topic space"
expect_refusal "an activation spec on a JNDI nothing carries" \
    jms_as_unknown "never receive a message"
expect "an activation spec on another scope's queue" \
                                                jms_as_other_scope   true
expect "delete the four"                        jms_absent           true
expect "replay delete"                          jms_absent           false

echo
echo "=== JMS on IBM MQ ==="
expect "create factory, queue, topic, spec"     mq                   true
expect "replay, WAS defaults not declared"      mq                   false
expect_value "four MQ resources" \
    "$(cell_value count MQConnectionFactory -)$(cell_value count MQQueue -)$(cell_value count MQTopic -)$(cell_value count J2CActivationSpec -)" "1111"
expect "factory moved to CLIENT on a host"      mq_client            true
expect "replay (idempotency)"                   mq_client            false
expect_refusal "a CLIENT factory with no host" \
    mq_client_nowhere "neither a host nor a connection_list"
expect "delete the four"                        mq_absent            true
expect "replay delete"                          mq_absent            false

echo
echo "=== the bus, deleted ==="
expect "delete the bus"                         sib_absent           true
expect "replay delete"                          sib_absent           false
expect_value "it took its members and destinations" \
    "$(cell_value count SIBusMember -)/$(cell_value count SIBQueue -)/$(cell_value count SIBMessagingEngine -)" "0/0/0"

echo
echo "=== the shared model, rendered for WAS traditional ==="
# The bus rendering's rules: no member means the run's cluster, and a value WAS
# constrains is checked before any session - here a misspelt reliability.
buses="$("$PY" -c '
import sys
sys.path.insert(0, sys.argv[1])
import traditional as T
r = T.sibus_specs([
    {"name": "A", "destinations": [{"name": "Q"}]},
    {"name": "B", "destinations": [{"name": "Q", "reliability": "VERY_RELIABLE"}]}], "ClusterEXT01")
print("|".join([str(len(r["errors"])), ",".join(b["bus"] for b in r["buses"]),
                r["buses"][0]["members"][0]["cluster"]]))
' "$COLLECTION/plugins/filter")"
expect_value "bus rendering rules" "$buses" "1|A|ClusterEXT01"
# The JMS grouping: one group per scope and provider, every group told about
# every declared destination (an activation spec may listen across scopes),
# and a default messaging resource with no bus refused.
groups="$("$PY" -c '
import sys
sys.path.insert(0, sys.argv[1])
import traditional as T
r = T.jms_groups({
    "queues": [{"name": "Q", "jndi_name": "jms/q", "queue": "Q", "bus": "B", "scope": "cell"}],
    "activation_specs": [{"name": "AS", "jndi_name": "jms/as", "destination_jndi": "jms/q", "bus": "B"},
                         {"name": "NoBus", "jndi_name": "jms/nb", "destination_jndi": "jms/q"}]},
    {"type": "cluster"}, "C", "Cell")
print("|".join([str(len(r["errors"])), str(len(r["groups"])),
                ",".join(sorted(g["scope"]["type"] for g in r["groups"])),
                str(all("jms/q" in g["known_destinations"] for g in r["groups"]))]))
' "$COLLECTION/plugins/filter")"
expect_value "JMS grouping rules" "$groups" "1|2|cell,cluster|True"
# The IBM MQ side of the grouping: the shared connection is merged into the
# factory and the spec - the resource keeping its own keys - not into a queue;
# a bus on an MQ resource, and an MQ queue naming no queue, refused.
mqgroups="$("$PY" -c '
import sys
sys.path.insert(0, sys.argv[1])
import traditional as T
r = T.jms_groups({
    "mq_connection": {"qmgr": "QM1", "transport": "CLIENT", "host": "mq", "port": 1414},
    "connection_factories": [{"name": "CF", "jndi_name": "jms/cf", "provider": "mq", "port": 1415}],
    "queues": [{"name": "Q", "jndi_name": "jms/q", "provider": "mq", "queue": "Q.IN"},
               {"name": "NoQ", "jndi_name": "jms/nq", "provider": "mq"},
               {"name": "Bus", "jndi_name": "jms/bq", "provider": "mq", "queue": "B", "bus": "B"}]},
    {"type": "cluster"}, "C", "Cell")
g = r["groups"][0]
cf = g["connection_factories"][0]
print("|".join([str(len(r["errors"])), g["provider"], cf["qmgr"], cf["host"], str(cf["port"]),
                str("qmgr" in g["queues"][0])]))
' "$COLLECTION/plugins/filter")"
expect_value "JMS grouping rules, IBM MQ" "$mqgroups" "2|mq|QM1|mq|1415|False"
# The library rendering's rules, on their own: a pattern that matched nothing
# is refused, an explicit list is kept in its order, an expansion is sorted -
# find returns files in filesystem order, and a class path that reshuffles
# between runs would read as a change every time.
libs="$("$PY" -c '
import sys
sys.path.insert(0, sys.argv[1])
import traditional as T
r = T.library_groups(
    [{"name": "empty", "dir": "/nowhere"},
     {"name": "explicit", "jars": ["/z/zz.jar", "/a/aa.jar"]},
     {"name": "pattern", "dir": "/s"}],
    {"empty": [], "pattern": ["/s/b.jar", "/s/a.jar"]},
    {"type": "cluster"}, "C", "Cell")
libs = dict((l["name"], l["class_path"]) for g in r["groups"] for l in g["libraries"])
print("|".join([str(len(r["errors"])), "empty" if "empty" not in libs else "kept",
                ",".join(libs["explicit"]), ",".join(libs["pattern"])]))
' "$COLLECTION/plugins/filter")"
expect_value "library rendering rules" "$libs" \
    "1|empty|/z/zz.jar,/a/aa.jar|/s/a.jar,/s/b.jar"
# plugins/filter/traditional.py turns the layer-1 declaration into the module
# arguments above. Asserted against the real example model, so a change to the
# vendor table or the pool translation shows up here, not on a cell.
render="$("$PY" -c '
import io, json, sys, yaml
sys.path.insert(0, sys.argv[1])
import traditional as T
model = yaml.safe_load(io.open(sys.argv[2]))
vendors = yaml.safe_load(io.open(sys.argv[3]))["jdbc_vendors"]
r = T.jdbc_groups(model["datasources"], vendors, {"type": "cluster"}, "ClusterEXT01", "Cell")
g = r["groups"][0]
p, d = g["providers"][0], g["datasources"][0]
print("|".join([str(len(r["errors"])), g["scope"]["cluster"], p["provider_type"],
                d["helper"].rsplit(".", 1)[1], str(d["pool"]["unusedTimeout"]),
                str(d["pool"]["connectionTimeout"]), p["name"]]))
' "$COLLECTION/plugins/filter" "$ROOT/model/example/common.yml" \
  "$COLLECTION/roles/model/vars/jdbc_vendors.yml")"
expect_value "example model -> WAS arguments" "$render" \
    "0|ClusterEXT01|DB2 UDB for iSeries (Toolbox)|DB2AS400DataStoreHelper|1800|30|as400ExtranetProvider"

echo
echo "=== the cluster, deleted with its members ==="
expect "delete"                             absent      true
expect "replay delete"                      absent      false
expect_value "deleting the cluster took its members" "$(cell_members)" "0"

echo
echo "=== guard: credentials on the command line must be refused ==="
# This is the regression that matters most. Anything on a wsadmin command line
# is visible in ps and lands in the Ansible log.
set +e
sh "$STUB/wsadmin.sh" -lang jython -username wsadmin -password secret \
   -f "$DRIVER" "$WORK/present.json" >"$WORK/guard.out" 2>&1
rc=$?
set -e
if [ "$rc" -eq 93 ]; then
    echo "  ok     refused with exit 93"
else
    echo "  FAIL   expected exit 93, got $rc"
    sed 's/^/         /' "$WORK/guard.out" | head -4
    fail=1
fi

echo
echo "=== guard: the properties file must be 0600 ==="
install -m 0644 /dev/null "$WORK/loose.props"
set +e
sh "$STUB/wsadmin.sh" -lang jython -wsadmin_properties "$WORK/loose.props" \
   -f "$DRIVER" "$WORK/present.json" >"$WORK/mode.out" 2>&1
rc=$?
set -e
if [ "$rc" -eq 98 ]; then
    echo "  ok     refused with exit 98"
else
    echo "  FAIL   expected exit 98, got $rc"
    sed 's/^/         /' "$WORK/mode.out" | head -4
    fail=1
fi

echo
echo "=== sync only on real change ==="
# "No change, no ripple" is the property a truthful `changed` buys. The fake
# cell counts syncs, so it can be asserted rather than described.
syncs="$("$PY" -c '
import json, os
print(json.load(open(os.environ["WAS_SIM_STATE"])).get("syncs", 0))
')"
# Twenty-nine effective changes above. The cluster: created, members created,
# a port pinned, a member drained, a member deleted, the cluster deleted (6).
# The aliases: created, password rotated, deleted (3). JDBC: provider created,
# its jar replaced, an alias created, a datasource created, its pool changed,
# the datasource deleted, the provider deleted, the alias deleted (8).
# Libraries: created, a jar added, deleted (3). The bus: created, a redelivery
# limit changed, deleted (3). JMS: created, a factory changed, deleted (3).
# JMS on IBM MQ: created, a factory moved to CLIENT, deleted (3).
# Every replay, every check run, the password left alone under on_create, the
# store drift left alone and every refusal must add none - a node
# synchronisation on a cell that did not change is a ripple through the estate
# for nothing.
if [ "$syncs" = "29" ]; then
    echo "  ok     29 syncs for 29 effective changes, none for the replays, the"
    echo "         check runs, the untouched password, the drift or the refusals"
else
    echo "  FAIL   expected 29 syncs, state reports $syncs"
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "CHECKS FAILED"
fi
exit "$fail"
