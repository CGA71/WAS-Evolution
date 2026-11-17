/*
 * The application portal's logic: no DOM, no network. What the page shows and
 * the answers it sends to the AWX workflows' surveys are decided here, so they
 * can be tested without a browser (ci/application-portal-tests.js) - the page
 * itself only draws and calls.
 *
 * Copyright (c) 2026, CGA
 * Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Applications = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // The inventory job template is recognised by its playbook: its name is the
  // site's to choose, the playbook is not.
  var INVENTORY_PLAYBOOK = "traditional_applications.yml";

  function isInventory(template) {
    return (template.playbook || "").split("/").pop() === INVENTORY_PLAYBOOK;
  }

  // From the successful inventory jobs to one report per cell: the newest job
  // that carries the cell wins.
  //
  // jobs: [{id, finished, inventory, inventoryName, organization, templateId,
  //         artifacts}], in any order.
  function latestReports(jobs) {
    var sorted = jobs.slice().sort(function (a, b) {
      return (b.finished || "").localeCompare(a.finished || "");
    });
    var seen = {};
    var reports = [];
    sorted.forEach(function (job) {
      var cells = ((job.artifacts || {}).wasevo_applications || {}).cells || {};
      Object.keys(cells).forEach(function (cell) {
        var key = job.inventory + "|" + cell;
        if (seen[key]) return;
        seen[key] = true;
        reports.push({
          key: key,
          cell: cell,
          organization: job.organization || "",
          inventory: job.inventory,
          inventoryName: job.inventoryName || "",
          templateId: job.templateId,
          job: job.id,
          finished: job.finished || "",
          report: cells[cell]
        });
      });
    });
    reports.sort(function (a, b) {
      return (a.report.environment || "").localeCompare(b.report.environment || "")
        || a.cell.localeCompare(b.cell);
    });
    return reports;
  }

  function describeTarget(target, cluster) {
    if (!target || target === "cluster") return "cluster " + (cluster || "");
    if (typeof target === "string") return target;
    if (target.type === "cluster") return "cluster " + target.cluster;
    return "serveur " + target.node + "/" + target.server;
  }

  // One row per application per cell: every application installed in the
  // cell, and every application of the catalogue that is not installed yet.
  //
  //   state   installed   in the cell and in the catalogue
  //           missing     in the catalogue, not in the cell - deployable
  //           foreign     in the cell, not in the catalogue - nothing to offer
  function rows(reports) {
    var out = [];
    reports.forEach(function (r) {
      var report = r.report || {};
      var catalogue = {};
      (report.catalogue || []).forEach(function (c) { catalogue[c.name] = c; });
      var installed = {};
      (report.applications || []).forEach(function (a) {
        installed[a.name] = true;
        var declared = catalogue[a.name];
        out.push({
          key: r.key + "|" + a.name,
          name: a.name,
          cell: r.cell,
          environment: report.environment || "",
          organization: r.organization,
          report: r,
          state: declared ? "installed" : "foreign",
          targets: (a.targets || []).map(function (t) { return t.replace(/^cluster=/, "cluster ").replace(/^node=([^,]*),server=/, "serveur $1/"); }),
          libraries: a.libraries || [],
          jndi: a.jndi || [],
          declared: declared || null
        });
      });
      (report.catalogue || []).forEach(function (c) {
        if (installed[c.name]) return;
        out.push({
          key: r.key + "|" + c.name,
          name: c.name,
          cell: r.cell,
          environment: report.environment || "",
          organization: r.organization,
          report: r,
          state: "missing",
          targets: [describeTarget(c.target, report.cluster)],
          libraries: [],
          jndi: [],
          declared: c
        });
      });
    });
    out.sort(function (a, b) {
      return a.environment.localeCompare(b.environment) || a.cell.localeCompare(b.cell)
        || a.name.localeCompare(b.name);
    });
    return out;
  }

  function matches(row, filter) {
    if (filter.environment && row.environment !== filter.environment) return false;
    if (filter.state && row.state !== filter.state) return false;
    if (filter.text) {
      var hay = [row.name, row.cell, row.environment, row.targets.join(" "),
                 row.libraries.join(" "), row.jndi.join(" ")].join(" ").toLowerCase();
      if (hay.indexOf(filter.text.toLowerCase()) < 0) return false;
    }
    return true;
  }

  // What a row offers. An application the catalogue does not declare offers
  // nothing: the roles act on declarations, and decommissioning reads what to
  // remove from one.
  function actionsFor(row) {
    if (row.state === "installed") return ["redeploy", "decommission"];
    if (row.state === "missing") return ["deploy"];
    return [];
  }

  function yes(value) { return value ? "true" : "false"; }

  // The survey answers of one workflow launch. Survey variables only, strings
  // for the multiple-choice questions, exactly as the survey's choices spell
  // them - AWX refuses an answer that is not one of the choices.
  function launchVars(row, action, input) {
    input = input || {};
    var vars = { was_environment: row.environment, application_name: row.name };
    if (action === "deploy" || action === "redeploy") {
      vars.application_force_reinstall = yes(action === "redeploy" && input.force);
    }
    if (action === "decommission") {
      vars.application_decommission_cluster = yes(input.cluster || input.node);
      vars.application_decommission_node = yes(input.node);
      vars.application_decommission_delete_profile = yes(input.node && input.deleteProfile);
    }
    return vars;
  }

  // What is missing or contradictory before a launch, in words. Empty: send it.
  function missing(row, action, input) {
    input = input || {};
    var gaps = [];
    if (!row.environment) gaps.push("l'environnement de la cellule (l'inventaire ne l'a pas publié)");
    if (actionsFor(row).indexOf(action) < 0) gaps.push("une action possible pour cette application");
    if (action === "decommission" && input.confirm !== row.name) {
      gaps.push("le nom de l'application, recopié pour confirmer");
    }
    return gaps;
  }

  // Which workflow an action launches.
  function workflowFor(action) {
    return action === "decommission" ? "decommission" : "deploy";
  }

  function finished(status) {
    return ["successful", "failed", "error", "canceled"].indexOf(status) >= 0;
  }

  return {
    INVENTORY_PLAYBOOK: INVENTORY_PLAYBOOK,
    isInventory: isInventory,
    latestReports: latestReports,
    rows: rows,
    matches: matches,
    actionsFor: actionsFor,
    launchVars: launchVars,
    missing: missing,
    workflowFor: workflowFor,
    finished: finished
  };
});
