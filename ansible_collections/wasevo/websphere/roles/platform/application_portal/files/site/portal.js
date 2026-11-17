/*
 * The application portal's page: it draws what applications.js decides, and
 * talks to the AWX API on this same origin with the viewer's own AWX session.
 *
 * No token, no server of its own: what a viewer sees and may launch is what
 * AWX lets that viewer see and launch. The page fills the survey of the AWX
 * workflows - environment, application, options - and AWX runs them, with
 * their approval node: nothing is removed from this page without a person
 * approving the plan in AWX.
 *
 * Everything a cell reports - a name, a JNDI binding - is written with
 * textContent, never as HTML.
 *
 * Copyright (c) 2026, CGA
 * Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
 */
(function () {
  "use strict";

  var A = window.Applications;
  var API = "/api/v2";
  var config = {
    awx_ui: "/",
    deploy_workflow: "WAS AIX - Application: deploy",
    decommission_workflow: "WAS AIX - Application: decommission"
  };
  var state = { inventories: [], workflows: {}, reports: [], rows: [], jobs: [] };

  var STATE_LABEL = { installed: "Installée", missing: "Non installée", foreign: "Hors catalogue" };
  var ACTION = {
    deploy: {
      title: "Déployer l'application",
      button: "Déployer",
      what: "Les ressources que l'application déclare (variables, alias J2C, bibliothèques, " +
            "datasources, JMS) sont créées, puis l'archive est installée depuis le partage des " +
            "applications et démarrée sur les membres."
    },
    redeploy: {
      title: "Redéployer l'application",
      button: "Redéployer",
      what: "Les ressources déclarées sont remises en conformité. L'application n'est réinstallée " +
            "(désinstallée puis installée) que si son archive a changé — ou si vous le forcez, ce " +
            "qui efface tout réglage fait à la main dans la console."
    },
    decommission: {
      title: "Décommissionner l'application",
      button: "Décommissionner",
      what: "Le workflow calcule d'abord un plan — ce qui part, ce qui reste parce qu'une autre " +
            "application l'utilise — puis attend une APPROBATION dans AWX avant de supprimer quoi " +
            "que ce soit : l'application, puis ses ressources JMS, JDBC, alias, bibliothèques et variables."
    }
  };

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function cookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function api(path, options) {
    options = options || {};
    var headers = { "Accept": "application/json" };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      // AWX takes a session-authenticated write only with Django's CSRF token,
      // which its own UI reads from this cookie the same way.
      headers["X-CSRFToken"] = cookie("csrftoken");
    }
    return fetch(API + path, {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    }).then(function (response) {
      if (response.status === 401) {
        var err = new Error("login");
        err.login = true;
        throw err;
      }
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          var detail = data.detail || JSON.stringify(data).slice(0, 300);
          throw new Error("AWX a refusé " + (options.method || "GET") + " " + path + " (" +
                          response.status + ") : " + detail);
        }
        return data;
      });
    });
  }

  function all(path) {
    var sep = path.indexOf("?") < 0 ? "?" : "&";
    return api(path + sep + "page_size=200").then(function (page) { return page.results || []; });
  }

  function showError(err) {
    if (err && err.login) {
      $("login").hidden = false;
      return;
    }
    var box = $("error");
    box.textContent = String(err && err.message || err);
    box.hidden = false;
  }

  // -- data -------------------------------------------------------------

  function loadTemplates() {
    var inventories = all("/job_templates/?playbook__contains=" + A.INVENTORY_PLAYBOOK).then(function (list) {
      state.inventories = list.filter(A.isInventory).map(function (t) {
        var org = (t.summary_fields || {}).organization || {};
        return { id: t.id, name: t.name, organization: org.name || "" };
      });
    });
    var workflows = Promise.all(["deploy", "decommission"].map(function (kind) {
      var name = config[kind + "_workflow"];
      return all("/workflow_job_templates/?name=" + encodeURIComponent(name)).then(function (list) {
        state.workflows[kind] = list[0] ? { id: list[0].id, name: list[0].name } : null;
      });
    }));
    return Promise.all([inventories, workflows]);
  }

  // The newest successful job of each inventory template, per AWX inventory,
  // read in full - the job list does not carry artifacts.
  function loadReports() {
    var reads = state.inventories.map(function (t) {
      return all("/jobs/?job_template=" + t.id + "&status=successful&order_by=-finished")
        .then(function (jobs) {
          var newest = {};
          jobs.forEach(function (j) {
            var inv = (j.summary_fields || {}).inventory || {};
            if (inv.id && !newest[inv.id]) newest[inv.id] = j.id;
          });
          return Promise.all(Object.keys(newest).map(function (inv) {
            return api("/jobs/" + newest[inv] + "/").then(function (j) {
              var summary = j.summary_fields || {};
              return {
                id: j.id,
                finished: j.finished,
                inventory: (summary.inventory || {}).id,
                inventoryName: (summary.inventory || {}).name,
                organization: t.organization,
                templateId: t.id,
                artifacts: j.artifacts || {}
              };
            });
          }));
        });
    });
    return Promise.all(reads).then(function (lists) {
      state.reports = A.latestReports([].concat.apply([], lists));
    });
  }

  function refresh() {
    $("error").hidden = true;
    $("reload").disabled = true;
    return api("/me/")
      .then(function (me) {
        var user = (me.results || [])[0] || {};
        $("who").textContent = user.username ? "Connecté : " + user.username : "";
        $("login").hidden = true;
      })
      .then(loadTemplates)
      .then(loadReports)
      .then(draw)
      .catch(showError)
      .then(function () { $("reload").disabled = false; });
  }

  // -- drawing ------------------------------------------------------------

  function filter() {
    return { environment: $("f-env").value, state: $("f-state").value, text: $("f-text").value.trim() };
  }

  function draw() {
    state.rows = A.rows(state.reports);
    drawTiles();
    drawCells();
    drawEnvironments();
    drawRows();
  }

  function drawTiles() {
    var counts = { installed: 0, missing: 0, foreign: 0 };
    state.rows.forEach(function (r) { counts[r.state] += 1; });
    var tiles = $("tiles");
    tiles.textContent = "";
    [["installed", "installées"], ["missing", "déclarées, non installées"],
     ["foreign", "installées hors catalogue"]].forEach(function (pair) {
      tiles.appendChild(el("div", { class: "tile " + pair[0] }, [
        el("b", { text: String(counts[pair[0]]) }), el("span", { text: pair[1] })
      ]));
    });
  }

  function drawCells() {
    var box = $("cells");
    box.textContent = "";
    state.reports.forEach(function (r) {
      var button = el("button", { type: "button", text: "Relire la cellule" });
      button.addEventListener("click", function () {
        launchInventory(r);
      });
      box.appendChild(el("div", { class: "cell-chip" }, [
        el("div", {}, [
          el("strong", { text: r.cell }), " ",
          el("small", { text: (r.report.environment ? r.report.environment + " · " : "") +
                              "lue le " + (r.report.scanned_on || r.finished.slice(0, 10)) })
        ]),
        button
      ]));
    });
    if (!state.reports.length) {
      box.appendChild(el("p", { class: "empty", text:
        "Aucune cellule lue. Lancez le job template « WAS AIX - Applications: inventory » dans " +
        "AWX, ou demandez le droit de le voir." }));
    }
    var gaps = [];
    if (!state.workflows.deploy) gaps.push("« " + config.deploy_workflow + " »");
    if (!state.workflows.decommission) gaps.push("« " + config.decommission_workflow + " »");
    if (gaps.length && state.reports.length) {
      box.appendChild(el("p", { class: "error", text:
        "Workflow invisible pour vous : " + gaps.join(", ") + ". Les actions correspondantes sont " +
        "désactivées — il faut le droit de l'exécuter dans AWX." }));
    }
  }

  function drawEnvironments() {
    var select = $("f-env");
    var current = select.value;
    var envs = {};
    state.reports.forEach(function (r) { if (r.report.environment) envs[r.report.environment] = true; });
    while (select.options.length > 1) select.remove(1);
    Object.keys(envs).sort().forEach(function (e) {
      select.appendChild(el("option", { value: e, text: e }));
    });
    select.value = envs[current] ? current : "";
  }

  function chips(values, mono) {
    return el("td", {}, values.map(function (v) {
      return el("span", { class: "chip" + (mono ? " mono" : ""), text: v });
    }));
  }

  function drawRows() {
    var body = $("rows");
    body.textContent = "";
    var f = filter();
    var shown = state.rows.filter(function (r) { return A.matches(r, f); });
    shown.forEach(function (row) {
      var actions = el("td");
      A.actionsFor(row).forEach(function (action, index) {
        var b = el("button", { type: "button", class: index === 0 ? "primary" : "",
                               text: ACTION[action].button });
        b.disabled = !state.workflows[A.workflowFor(action)];
        b.addEventListener("click", function () { openDialog(row, action); });
        actions.appendChild(b);
      });
      if (row.state === "foreign") {
        actions.appendChild(el("small", { text: "Non déclarée dans was_applications : aucune action" }));
      }
      body.appendChild(el("tr", {}, [
        el("td", {}, [el("span", { class: "badge " + row.state, text: STATE_LABEL[row.state] })]),
        el("td", {}, [el("strong", { text: row.name }),
                      row.declared && row.declared.archive
                        ? el("small", { class: "mono block", text: row.declared.archive }) : null]),
        el("td", { text: row.environment }),
        el("td", { text: row.cell }),
        el("td", { text: row.targets.join(", ") }),
        chips(row.libraries),
        chips(row.jndi, true),
        actions
      ]));
    });
    var empty = $("empty");
    empty.hidden = shown.length > 0;
    empty.textContent = state.rows.length ? "Aucune application ne correspond aux filtres." : "";
  }

  // -- the launch dialog -------------------------------------------------

  var pending = null;

  function checkbox(label, id) {
    var box = el("input", { type: "checkbox", id: id });
    return { input: box, node: el("label", { class: "check" }, [box, " " + label]) };
  }

  function openDialog(row, action) {
    pending = { row: row, action: action, inputs: {} };
    $("dlg-title").textContent = ACTION[action].title;
    $("dlg-what").textContent = ACTION[action].what;
    var dl = $("dlg-app");
    dl.textContent = "";
    [["Application", row.name], ["Environnement", row.environment], ["Cellule", row.cell],
     ["Cible", row.targets.join(", ")],
     ["Archive", (row.declared && row.declared.archive) || "?"]].forEach(function (pair) {
      dl.appendChild(el("dt", { text: pair[0] }));
      dl.appendChild(el("dd", { text: pair[1] }));
    });
    var fields = $("dlg-fields");
    fields.textContent = "";
    if (action === "redeploy") {
      var force = checkbox("Réinstaller même si l'archive n'a pas changé", "dlg-force");
      pending.inputs.force = force.input;
      fields.appendChild(force.node);
    }
    if (action === "decommission") {
      var cluster = checkbox("Supprimer aussi le cluster, si aucune autre application n'y est mappée", "dlg-cluster");
      var node = checkbox("Supprimer aussi l'agent de nœud et son nœud, s'il ne porte plus rien (implique le cluster)", "dlg-node");
      var profile = checkbox("Et supprimer le profil du nœud sur disque", "dlg-profile");
      profile.input.disabled = true;
      node.input.addEventListener("change", function () {
        profile.input.disabled = !node.input.checked;
        if (node.input.checked) cluster.input.checked = true;
        if (!node.input.checked) profile.input.checked = false;
      });
      var confirm = el("input", { type: "text", autocomplete: "off", placeholder: row.name });
      pending.inputs.cluster = cluster.input;
      pending.inputs.node = node.input;
      pending.inputs.deleteProfile = profile.input;
      pending.inputs.confirm = confirm;
      fields.appendChild(cluster.node);
      fields.appendChild(node.node);
      fields.appendChild(profile.node);
      fields.appendChild(el("label", {}, ["Recopiez le nom de l'application pour confirmer", confirm]));
    }
    $("dlg-missing").hidden = true;
    $("dlg").showModal();
  }

  function values() {
    var out = {};
    Object.keys(pending.inputs).forEach(function (k) {
      var input = pending.inputs[k];
      out[k] = input.type === "checkbox" ? input.checked : input.value.trim();
    });
    return out;
  }

  $("dlg-form").addEventListener("submit", function (event) {
    var submitter = event.submitter || {};
    if (submitter.value !== "launch" || !pending) return;
    var input = values();
    var gaps = A.missing(pending.row, pending.action, input);
    if (gaps.length) {
      event.preventDefault();
      $("dlg-missing").textContent = "Il manque : " + gaps.join(", ") + ".";
      $("dlg-missing").hidden = false;
      return;
    }
    var row = pending.row;
    launchWorkflow(state.workflows[A.workflowFor(pending.action)],
                   A.launchVars(row, pending.action, input),
                   ACTION[pending.action].title + " — " + row.name + " (" + row.environment + ")");
  });

  // -- launches ------------------------------------------------------------

  function track(entry, request, kind) {
    state.jobs.unshift(entry);
    drawJobs();
    request.then(function (answer) {
      entry.id = answer.workflow_job || answer.job || answer.id;
      entry.kind = kind;
      entry.status = answer.status || "pending";
      drawJobs();
      follow(entry);
    }).catch(function (err) {
      entry.status = "refusé";
      entry.error = err.login ? "Session AWX expirée : reconnectez-vous." : String(err.message || err);
      drawJobs();
    });
  }

  function launchWorkflow(workflow, extraVars, label) {
    track({ label: label, id: null, status: "envoi…" },
          api("/workflow_job_templates/" + workflow.id + "/launch/", {
            method: "POST", body: { extra_vars: extraVars }
          }), "workflow");
  }

  function launchInventory(report) {
    track({ label: "Lecture de la cellule " + report.cell, id: null, status: "envoi…" },
          api("/job_templates/" + report.templateId + "/launch/", {
            method: "POST",
            body: { inventory: report.inventory,
                    extra_vars: report.report.environment ? { was_environment: report.report.environment } : {} }
          }), "job");
  }

  // A workflow waiting on its approval node is "running" for AWX; the page
  // says what it is waiting for, so nobody wonders why nothing moves.
  function follow(entry) {
    var path = entry.kind === "workflow" ? "/workflow_jobs/" : "/jobs/";
    api(path + entry.id + "/").then(function (job) {
      entry.status = job.status;
      if (A.finished(job.status)) {
        drawJobs();
        if (job.status === "successful") refresh();
        return null;
      }
      if (entry.kind !== "workflow") return null;
      return all("/workflow_jobs/" + entry.id + "/workflow_nodes/").then(function (nodes) {
        entry.approval = nodes.some(function (n) {
          var job = (n.summary_fields || {}).job || {};
          return job.type === "workflow_approval" && job.status === "pending";
        });
      });
    }).then(function () {
      if (!A.finished(entry.status)) {
        drawJobs();
        setTimeout(function () { follow(entry); }, 4000);
      }
    }).catch(function (err) {
      entry.status = "suivi interrompu";
      entry.error = String(err.message || err);
      drawJobs();
    });
  }

  var JOB_STATUS = {
    pending: "en attente", waiting: "en attente", running: "en cours", successful: "réussi",
    failed: "échoué", error: "erreur", canceled: "annulé"
  };

  function jobLink(entry) {
    return (config.awx_ui || "/") + "#/jobs/" + (entry.kind === "workflow" ? "workflow" : "playbook") +
      "/" + entry.id + "/output";
  }

  function drawJobs() {
    $("jobs-section").hidden = state.jobs.length === 0;
    var list = $("jobs");
    list.textContent = "";
    state.jobs.forEach(function (entry) {
      var head = [el("strong", { text: entry.label }), " — " + (JOB_STATUS[entry.status] || entry.status)];
      if (entry.id) {
        head.push(" · ");
        head.push(el("a", { href: jobLink(entry), target: "_blank", rel: "noopener",
                            text: (entry.kind === "workflow" ? "workflow " : "job ") + entry.id + " dans AWX" }));
      }
      var item = el("li", {}, [el("div", {}, head)]);
      if (entry.approval) {
        item.appendChild(el("p", { class: "pending", text:
          "En attente d'approbation : lisez le plan (nœud 0) dans AWX, puis approuvez ou refusez." }));
        item.appendChild(el("a", { href: (config.awx_ui || "/") + "#/workflow_approvals",
                                   target: "_blank", rel: "noopener", text: "Approbations AWX" }));
      }
      if (entry.error) item.appendChild(el("p", { class: "error", text: entry.error }));
      list.appendChild(item);
    });
  }

  // -- wiring ----------------------------------------------------------------

  ["f-env", "f-state"].forEach(function (id) { $(id).addEventListener("change", drawRows); });
  $("f-text").addEventListener("input", drawRows);
  $("reload").addEventListener("click", refresh);

  fetch("portal.json", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .catch(function () { return {}; })
    .then(function (loaded) {
      Object.keys(loaded || {}).forEach(function (k) { config[k] = loaded[k]; });
      $("login-link").setAttribute("href", (config.awx_ui || "/") + "#/login");
      return refresh();
    });
})();
