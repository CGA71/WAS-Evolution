// The certificate portal's logic, without a browser and without AWX.
//
//   node ci/portal-tests.js
//
// What is decided here is what the page shows and what it asks AWX to run:
// the status of a certificate for TODAY, which job's report wins for a cell,
// which actions a certificate offers, and the extra vars of a launch. The page
// itself only draws that and calls the API.
"use strict";

const path = require("path");
const C = require(path.join(__dirname, "..", "ansible_collections", "wasevo", "websphere",
  "roles", "platform", "certificate_portal", "files", "site", "certificates.js"));

let failed = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"}   ${label}${ok ? "" : `\n         expected ${JSON.stringify(want)}\n         got      ${JSON.stringify(got)}`}`);
  if (!ok) failed = 1;
}

const now = new Date(Date.UTC(2026, 10, 13, 15, 0, 0));

console.log("=== days left and status, for today ===");
check("45 days ahead", C.daysLeft("2026-12-28", now), 45);
check("expired yesterday", C.daysLeft("2026-11-12", now), -1);
check("no date", C.daysLeft("", now), null);
check("not a date", C.daysLeft("Feb 2, 2027", now), null);
check("expired", C.statusOf(-1, 90), "expired");
check("expires today is critical, not expired", C.statusOf(0, 90), "critical");
check("30 days is critical", C.statusOf(30, 90), "critical");
check("31 days is a warning", C.statusOf(31, 90), "warning");
check("90 days is still due", C.statusOf(90, 90), "warning");
check("91 days is fine", C.statusOf(91, 90), "ok");
check("an unreadable date is never ok", C.statusOf(null, 90), "unknown");

console.log("=== templates are recognised by their playbook, not their name ===");
check("inventory", C.roleOf({ playbook: "ansible_collections/wasevo/websphere/playbooks/traditional_certificates.yml" }), "inventory");
check("renewal", C.roleOf({ playbook: "x/traditional_certificate_renewal.yml" }), "renew");
check("anything else", C.roleOf({ playbook: "x/traditional_ssl.yml" }), null);

console.log("=== the newest job carrying a cell wins ===");
const cert = (alias, notAfter, extra) => Object.assign({
  id: `personal|(cell):A|CellDefaultKeyStore|${alias}`, kind: "personal", domain: "engine",
  scope: "(cell):A", keystore: "CellDefaultKeyStore", alias, not_after: notAfter, method: "renew",
  subject: "CN=a", issuer: "CN=root, OU=Root Certificate", used_by: []
}, extra || {});
const jobs = [
  { id: 10, finished: "2026-11-10T08:00:00Z", inventory: 1, organization: "Org1",
    artifacts: { wasevo_certificates: { cells: { A: { certificates: [cert("default", "2026-11-20")], environment: "ENVCODE" } } } } },
  { id: 12, finished: "2026-11-12T08:00:00Z", inventory: 1, organization: "Org1",
    artifacts: { wasevo_certificates: { cells: { A: { certificates: [cert("default", "2027-11-12")], environment: "ENVCODE" } } } } },
  { id: 11, finished: "2026-11-11T08:00:00Z", inventory: 2, organization: "Org2",
    artifacts: { wasevo_certificates: { cells: { B: { certificates: [
      cert("old", "2026-11-01", { scope: "(cell):B", id: "personal|(cell):B|K|old" }),
      cert("ca-signed", "2026-12-28", { scope: "(cell):B", id: "personal|(cell):B|K|ca", method: "request",
                                        domain: "application", pending_requests: ["ca-signed_20261228"] })] } } } } },
  { id: 13, finished: "2026-11-13T08:00:00Z", inventory: 2, organization: "Org2", artifacts: {} }
];
const reports = C.latestReports(jobs);
check("one report per cell", reports.map(r => [r.cell, r.job]).sort(), [["A", 12], ["B", 11]]);
check("a job with no artifacts hides nothing", reports.find(r => r.cell === "B").job, 11);

const rows = C.rows(reports, now, 90);
check("most urgent first", rows.map(r => r.cert.alias), ["old", "ca-signed", "default"]);
check("status recomputed for today", rows.map(r => r.status), ["expired", "warning", "ok"]);
check("the environment travels with the row", rows.find(r => r.cell === "A").environment, "ENVCODE");

console.log("=== filters ===");
check("due only hides what is fine", rows.filter(r => C.matches(r, { onlyDue: true })).length, 2);
check("by organisation", rows.filter(r => C.matches(r, { organization: "Org1" })).map(r => r.cell), ["A"]);
check("by domain", rows.filter(r => C.matches(r, { domain: "application" })).map(r => r.cert.alias), ["ca-signed"]);
check("free text, any case", rows.filter(r => C.matches(r, { text: "CA-SIGNED" })).length, 1);

console.log("=== what a certificate offers ===");
check("cell-signed: renew", C.actionsFor({ method: "renew" }), ["renew"]);
check("CA-signed: request", C.actionsFor({ method: "request" }), ["request"]);
check("CA-signed with a request waiting: receive first", C.actionsFor({ method: "request", pending_requests: ["x_1"] }), ["receive", "request"]);
check("signer: retrieve again", C.actionsFor({ method: "refresh_signer" }), ["refresh_signer"]);
check("the cell's root: nothing to press", C.actionsFor({ method: "manual" }), []);

console.log("=== the extra vars of a launch ===");
const a = rows.find(r => r.cell === "A");
check("renew: the certificate and the environment",
  C.renewalVars(a, "renew", {}),
  { certificate_renewal: { action: "renew", keystore: "CellDefaultKeyStore", scope: "(cell):A", alias: "default" },
    was_environment: "ENVCODE" });
check("force only when asked", C.renewalVars(a, "renew", { force: true }).certificate_renewal.force, true);
const b = rows.find(r => r.cert.alias === "ca-signed");
check("receive: the waiting request by default",
  C.renewalVars(b, "receive", { signed_certificate: "-----BEGIN CERTIFICATE-----" }).certificate_renewal.request_alias,
  "ca-signed_20261228");
check("receive: no CA when none given",
  "ca_certificate" in C.renewalVars(b, "receive", { signed_certificate: "x" }).certificate_renewal, false);
check("refresh_signer: port defaults to 443",
  C.renewalVars(a, "refresh_signer", { peer_host: "p" }).certificate_renewal.peer_port, 443);
check("no environment, none sent", "was_environment" in C.renewalVars(b, "renew", {}), false);

console.log("=== a launch is refused before it is sent, with the reason ===");
check("receive without a PEM", C.missing("receive", { signed_certificate: "hello" }).length, 1);
check("receive with one", C.missing("receive", { signed_certificate: "-----BEGIN CERTIFICATE-----\nx" }), []);
check("refresh without a host", C.missing("refresh_signer", {}).length, 1);
check("renew needs nothing", C.missing("renew", {}), []);
check("job states that end", ["successful", "failed", "running"].map(C.finished), [true, true, false]);

console.log(failed ? "\nCHECKS FAILED" : "\nALL CHECKS PASSED");
process.exit(failed);
