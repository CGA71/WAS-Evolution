// The application portal's logic, without a browser and without AWX.
//
//   node ci/application-portal-tests.js
//
// What is decided here is what the page shows and what it sends to the AWX
// workflows: which report wins for a cell, the state of each application,
// which actions it offers, and the survey answers of a launch - which AWX
// refuses if a multiple-choice answer is not spelt as one of the choices.
"use strict";

const path = require("path");
const A = require(path.join(__dirname, "..", "ansible_collections", "wasevo", "websphere",
  "roles", "platform", "application_portal", "files", "site", "applications.js"));

let failed = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? "ok  " : "FAIL"}   ${label}${ok ? "" : `\n         expected ${JSON.stringify(want)}\n         got      ${JSON.stringify(got)}`}`);
  if (!ok) failed = 1;
}

console.log("=== the inventory template is recognised by its playbook ===");
check("traditional_applications.yml", A.isInventory({ playbook: "ansible_collections/wasevo/websphere/playbooks/traditional_applications.yml" }), true);
check("not the deploy playbook", A.isInventory({ playbook: "x/traditional_application_deploy.yml" }), false);

const report = (cell, env, applications, catalogue) => ({
  cell, environment: env, cluster: "ClusterEXT01", scanned_on: "2026-11-17", applications, catalogue
});
const jobs = [
  { id: 10, finished: "2026-11-16T10:00:00Z", inventory: 1, templateId: 7,
    artifacts: { wasevo_applications: { cells: { CellA: report("CellA", "ENVCODE01", [], []) } } } },
  { id: 12, finished: "2026-11-17T10:00:00Z", inventory: 1, templateId: 7,
    artifacts: { wasevo_applications: { cells: { CellA: report("CellA", "ENVCODE01",
      [{ name: "Orders", declared: true, targets: ["cluster=ClusterEXT01"], libraries: ["ordersLib"], jndi: ["jdbc/orders"] },
       { name: "Legacy", declared: false, targets: ["node=N1,server=S1"], libraries: [], jndi: [] }],
      [{ name: "Orders", archive: "orders/Orders.ear", target: "cluster", installed: true },
       { name: "Catalogue", archive: "cat/catalogue.war", target: "cluster", installed: false }]) } } } },
  { id: 11, finished: "2026-11-17T09:00:00Z", inventory: 2, templateId: 7,
    artifacts: { wasevo_applications: { cells: { CellB: report("CellB", "ENVCODE02", [], []) } } } }
];

console.log("=== the newest report per cell wins ===");
const reports = A.latestReports(jobs);
check("one report per cell", reports.map(r => r.cell), ["CellA", "CellB"]);
check("CellA comes from the newest job", reports[0].job, 12);
check("the template is kept, to relaunch the inventory", reports[0].templateId, 7);

console.log("=== one row per application, its state from the catalogue ===");
const rows = A.rows(reports);
check("installed, foreign and missing", rows.map(r => `${r.name}:${r.state}`),
  ["Catalogue:missing", "Legacy:foreign", "Orders:installed"]);
const orders = rows.find(r => r.name === "Orders");
const legacy = rows.find(r => r.name === "Legacy");
const catalogue = rows.find(r => r.name === "Catalogue");
check("targets read as a person reads them", [orders.targets, legacy.targets],
  [["cluster ClusterEXT01"], ["serveur N1/S1"]]);
check("a missing application shows the declared target", catalogue.targets, ["cluster ClusterEXT01"]);

console.log("=== what each row offers ===");
check("installed: redeploy, decommission", A.actionsFor(orders), ["redeploy", "decommission"]);
check("declared, not installed: deploy", A.actionsFor(catalogue), ["deploy"]);
check("not in the catalogue: nothing", A.actionsFor(legacy), []);
check("deploy and redeploy use the deploy workflow", [A.workflowFor("deploy"), A.workflowFor("redeploy")], ["deploy", "deploy"]);
check("decommission uses its own", A.workflowFor("decommission"), "decommission");

console.log("=== the survey answers ===");
check("deploy", A.launchVars(catalogue, "deploy", {}),
  { was_environment: "ENVCODE01", application_name: "Catalogue", application_force_reinstall: "false" });
check("deploy never forces", A.launchVars(catalogue, "deploy", { force: true }).application_force_reinstall, "false");
check("redeploy, forced", A.launchVars(orders, "redeploy", { force: true }).application_force_reinstall, "true");
check("decommission, the application alone", A.launchVars(orders, "decommission", {}),
  { was_environment: "ENVCODE01", application_name: "Orders", application_decommission_cluster: "false",
    application_decommission_node: "false", application_decommission_delete_profile: "false" });
const nodeOnly = A.launchVars(orders, "decommission", { node: true });
check("the node implies the cluster", [nodeOnly.application_decommission_cluster, nodeOnly.application_decommission_node], ["true", "true"]);
check("the profile only with the node", A.launchVars(orders, "decommission", { deleteProfile: true }).application_decommission_delete_profile, "false");

console.log("=== what is refused before a launch ===");
check("a decommissioning needs the name typed again", A.missing(orders, "decommission", { confirm: "orders" }).length, 1);
check("typed right, it goes", A.missing(orders, "decommission", { confirm: "Orders" }), []);
check("an application outside the catalogue cannot be decommissioned", A.missing(legacy, "decommission", { confirm: "Legacy" }).length, 1);
check("a deploy needs no confirmation", A.missing(catalogue, "deploy", {}), []);

console.log("=== filters ===");
check("by environment", rows.filter(r => A.matches(r, { environment: "ENVCODE01" })).length, 3);
check("by state", rows.filter(r => A.matches(r, { state: "foreign" })).map(r => r.name), ["Legacy"]);
check("by JNDI name", rows.filter(r => A.matches(r, { text: "jdbc/orders" })).map(r => r.name), ["Orders"]);

console.log(failed ? "\nCHECKS FAILED" : "\nALL CHECKS PASSED");
process.exit(failed);
