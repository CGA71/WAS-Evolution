/*
 * The certificate portal's logic: no DOM, no network. What the page shows and
 * what it asks AWX to run are decided here, so they can be tested without a
 * browser (ci/portal-tests.js) - the page itself only draws and calls.
 *
 * Copyright (c) 2026, CGA
 * Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Certificates = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DAY = 24 * 3600 * 1000;

  // The playbooks the portal recognises a job template by. The name of a
  // template is the organisation's to choose; the playbook is not.
  var PLAYBOOKS = {
    inventory: "traditional_certificates.yml",
    renew: "traditional_certificate_renewal.yml"
  };

  function roleOf(template) {
    var playbook = (template.playbook || "").split("/").pop();
    if (playbook === PLAYBOOKS.inventory) return "inventory";
    if (playbook === PLAYBOOKS.renew) return "renew";
    return null;
  }

  // Days left counted from today, not from the scan: a report read a week
  // after it was made still tells the truth about what expires.
  function daysLeft(notAfter, now) {
    if (!notAfter || !/^\d{4}-\d{2}-\d{2}$/.test(notAfter)) return null;
    var parts = notAfter.split("-");
    var end = Date.UTC(+parts[0], +parts[1] - 1, +parts[2]);
    var today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.round((end - today) / DAY);
  }

  function statusOf(days, windowDays) {
    if (days === null || days === undefined) return "unknown";
    if (days < 0) return "expired";
    if (days <= 30) return "critical";
    if (days <= windowDays) return "warning";
    return "ok";
  }

  var STATUS_ORDER = { expired: 0, critical: 1, unknown: 2, warning: 3, ok: 4 };

  // From the latest successful jobs of the inventory and renewal templates to
  // one report per cell: the newest job that carries the cell wins, whichever
  // template ran it - a renewal ends with a fresh inventory of its cell.
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
      var cells = ((job.artifacts || {}).wasevo_certificates || {}).cells || {};
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
          job: job.id,
          finished: job.finished || "",
          report: cells[cell]
        });
      });
    });
    return reports;
  }

  // Every certificate of every report, its status recomputed for today.
  function rows(reports, now, windowDays) {
    var out = [];
    reports.forEach(function (r) {
      (r.report.certificates || []).forEach(function (c) {
        var days = daysLeft(c.not_after, now);
        out.push({
          key: r.key + "|" + c.id,
          cert: c,
          cell: r.cell,
          organization: r.organization,
          inventory: r.inventory,
          inventoryName: r.inventoryName,
          environment: r.report.environment || "",
          days: days,
          status: statusOf(days, windowDays)
        });
      });
    });
    out.sort(function (a, b) {
      return (STATUS_ORDER[a.status] - STATUS_ORDER[b.status])
        || ((a.days === null ? 1e9 : a.days) - (b.days === null ? 1e9 : b.days))
        || a.key.localeCompare(b.key);
    });
    return out;
  }

  function matches(row, filter) {
    if (filter.onlyDue && row.status === "ok") return false;
    if (filter.organization && row.organization !== filter.organization) return false;
    if (filter.domain && row.cert.domain !== filter.domain) return false;
    if (filter.text) {
      var hay = [row.cell, row.organization, row.cert.keystore, row.cert.alias,
                 row.cert.subject, row.cert.issuer, row.cert.scope].join(" ").toLowerCase();
      if (hay.indexOf(filter.text.toLowerCase()) < 0) return false;
    }
    return true;
  }

  // What a certificate offers, in the order an operator would take it.
  function actionsFor(cert) {
    switch (cert.method) {
      case "renew": return ["renew"];
      case "request":
        return (cert.pending_requests || []).length ? ["receive", "request"] : ["request"];
      case "refresh_signer": return ["refresh_signer"];
      default: return [];
    }
  }

  // The extra vars of one launch of the renewal template. Only what the
  // action needs: a launch is recorded in AWX, and noise there is noise in
  // the audit trail.
  function renewalVars(row, action, input) {
    input = input || {};
    var c = row.cert;
    var renewal = { action: action, keystore: c.keystore, scope: c.scope, alias: c.alias };
    if (input.force) renewal.force = true;
    if (action === "receive") {
      renewal.request_alias = input.request_alias || (c.pending_requests || [])[0] || "";
      renewal.signed_certificate = input.signed_certificate || "";
      if (input.ca_certificate) renewal.ca_certificate = input.ca_certificate;
    }
    if (action === "refresh_signer") {
      renewal.peer_host = input.peer_host || "";
      renewal.peer_port = parseInt(input.peer_port, 10) || 443;
    }
    var vars = { certificate_renewal: renewal };
    if (row.environment) vars.was_environment = row.environment;
    return vars;
  }

  // What is missing before a launch can be sent, in words. Empty: send it.
  function missing(action, input) {
    input = input || {};
    var gaps = [];
    if (action === "receive" && !/BEGIN CERTIFICATE/.test(input.signed_certificate || "")) {
      gaps.push("le certificat signé par la CA, au format PEM");
    }
    if (action === "refresh_signer" && !input.peer_host) {
      gaps.push("l'hôte du pair qui présente le certificat");
    }
    return gaps;
  }

  function finished(status) {
    return ["successful", "failed", "error", "canceled"].indexOf(status) >= 0;
  }

  return {
    PLAYBOOKS: PLAYBOOKS,
    roleOf: roleOf,
    daysLeft: daysLeft,
    statusOf: statusOf,
    latestReports: latestReports,
    rows: rows,
    matches: matches,
    actionsFor: actionsFor,
    renewalVars: renewalVars,
    missing: missing,
    finished: finished
  };
});
