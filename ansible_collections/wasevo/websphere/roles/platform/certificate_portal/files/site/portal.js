/*
 * The certificate portal's page: it draws what certificates.js decides, and
 * talks to the AWX API on this same origin with the viewer's own AWX session.
 *
 * No token, no server of its own: what a viewer sees and may launch is what
 * AWX lets that viewer see and launch. A user of one organisation reads the
 * job artifacts of that organisation's templates and nothing else.
 *
 * Everything a cell reports - a subject, an issuer, an alias - is written with
 * textContent, never as HTML: a certificate is data from outside.
 *
 * Copyright (c) 2026, CGA
 * Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)
 */
(function () {
  "use strict";

  var C = window.Certificates;
  var API = "/api/v2";
  var config = { renew_within_days: 90, awx_ui: "/" };
  var state = { templates: [], reports: [], rows: [], jobs: [] };

  var STATUS_LABEL = {
    expired: "Expiré", critical: "< 30 jours", warning: "À échéance", ok: "OK", unknown: "Date illisible"
  };
  var DOMAIN_LABEL = { engine: "Moteur", application: "Application", trust: "Confiance" };
  var ACTION = {
    renew: {
      title: "Renouveler par la cellule",
      button: "Renouveler",
      what: "Le certificat est signé par la cellule (chaîné à sa racine, ou autosigné). " +
            "La cellule l'émet de nouveau sous le même alias : les configurations SSL qui le " +
            "présentent continuent de l'utiliser."
    },
    request: {
      title: "Demander à la CA (requête de certificat)",
      button: "Générer la requête",
      what: "Le certificat est signé par une CA hors de la cellule. Le job génère une requête " +
            "de certificat (CSR) dans la keystore ; la clé privée n'en sort pas. Transmettez la " +
            "requête à votre CA, puis revenez recevoir sa réponse."
    },
    receive: {
      title: "Recevoir le certificat signé par la CA",
      button: "Recevoir",
      what: "Le certificat signé est reçu dans la keystore, puis chaque configuration SSL passe " +
            "de l'ancien certificat au nouveau, et l'ancien est supprimé."
    },
    refresh_signer: {
      title: "Récupérer de nouveau le signataire",
      button: "Récupérer",
      what: "Un signataire est le certificat d'un pair (LDAP, base de données, MQ, partenaire). " +
            "Seul le pair peut le renouveler ; une fois fait, le job supprime l'ancien signataire " +
            "et le récupère de nouveau sur le port du pair, sous le même alias."
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

  function jobLink(id) {
    return (config.awx_ui || "/") + "#/jobs/playbook/" + id + "/output";
  }

  // -- data -------------------------------------------------------------

  function loadTemplates() {
    return all("/job_templates/?playbook__contains=traditional_certificate").then(function (list) {
      state.templates = list.map(function (t) {
        var org = (t.summary_fields || {}).organization || {};
        return { id: t.id, name: t.name, role: C.roleOf(t), organization: org.name || "", orgId: org.id };
      }).filter(function (t) { return t.role; });
    });
  }

  function templateFor(role, organization) {
    var found = state.templates.filter(function (t) {
      return t.role === role && t.organization === organization;
    });
    return found[0] || null;
  }

  // The newest successful job of each template for each inventory, read in
  // full - the job list does not carry artifacts.
  function loadReports() {
    var reads = state.templates.map(function (t) {
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
      state.reports = C.latestReports([].concat.apply([], lists));
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
    return {
      organization: $("f-org").value,
      domain: $("f-domain").value,
      text: $("f-text").value.trim(),
      onlyDue: $("f-due").checked
    };
  }

  function draw() {
    var now = new Date();
    state.rows = C.rows(state.reports, now, config.renew_within_days);
    drawTiles();
    drawCells();
    drawOrganizations();
    drawRows();
  }

  function drawTiles() {
    var counts = { expired: 0, critical: 0, warning: 0, unknown: 0, ok: 0 };
    state.rows.forEach(function (r) { counts[r.status] += 1; });
    var tiles = $("tiles");
    tiles.textContent = "";
    [["expired", "expirés"], ["critical", "dans moins de 30 jours"],
     ["warning", "dans moins de " + config.renew_within_days + " jours"],
     ["unknown", "date illisible"], ["ok", "à jour"]].forEach(function (pair) {
      tiles.appendChild(el("div", { class: "tile " + pair[0] }, [
        el("b", { text: String(counts[pair[0]]) }), el("span", { text: pair[1] })
      ]));
    });
  }

  function drawCells() {
    var box = $("cells");
    box.textContent = "";
    state.reports.forEach(function (r) {
      var inventoryTemplate = templateFor("inventory", r.organization);
      var button = null;
      if (inventoryTemplate) {
        button = el("button", { type: "button", text: "Relancer l'inventaire" });
        button.addEventListener("click", function () {
          launch(inventoryTemplate, r.inventory,
                 r.report.environment ? { was_environment: r.report.environment } : {},
                 "Inventaire de " + r.cell);
        });
      }
      box.appendChild(el("div", { class: "cell-chip" }, [
        el("div", {}, [
          el("strong", { text: r.cell }), " ",
          el("small", { text: (r.organization ? r.organization + " · " : "") +
                              "lu le " + (r.report.scanned_on || r.finished.slice(0, 10)) })
        ]),
        button
      ]));
    });
    if (!state.reports.length) {
      box.appendChild(el("p", { class: "empty", text:
        "Aucun inventaire de certificats visible. Lancez le job template « Certificates - inventory » " +
        "dans AWX, ou demandez l'accès à l'organisation qui le porte." }));
    }
  }

  function drawOrganizations() {
    var select = $("f-org");
    var current = select.value;
    var orgs = {};
    state.reports.forEach(function (r) { if (r.organization) orgs[r.organization] = true; });
    while (select.options.length > 1) select.remove(1);
    Object.keys(orgs).sort().forEach(function (o) {
      select.appendChild(el("option", { value: o, text: o }));
    });
    select.value = orgs[current] ? current : "";
  }

  function drawRows() {
    var body = $("rows");
    body.textContent = "";
    var f = filter();
    var shown = state.rows.filter(function (r) { return C.matches(r, f); });
    shown.forEach(function (row) {
      var c = row.cert;
      var used = el("td", {}, (c.used_by || []).map(function (u) { return el("span", { class: "chip", text: u }); }));
      var name = el("td", { class: "mono" }, [c.keystore, el("br"), el("strong", { text: c.alias })]);
      (c.pending_requests || []).forEach(function (p) {
        name.appendChild(el("span", { class: "pending", text: "Requête en attente de la CA : " + p }));
      });
      var actions = el("td");
      C.actionsFor(c).forEach(function (action) {
        var b = el("button", { type: "button", class: action === C.actionsFor(c)[0] ? "primary" : "",
                               text: ACTION[action].button });
        b.addEventListener("click", function () { openDialog(row, action); });
        actions.appendChild(b);
      });
      if (!C.actionsFor(c).length) {
        actions.appendChild(el("small", { text: c.method === "manual"
          ? "Manuel : racine ou CA, à planifier" : "" }));
      }
      body.appendChild(el("tr", {}, [
        el("td", {}, [el("span", { class: "badge " + row.status, text: STATUS_LABEL[row.status] })]),
        el("td", { class: "num", text: row.days === null ? "?" : String(row.days) }),
        el("td", { class: "mono date", text: c.not_after || c.validity || "" }),
        el("td", {}, [el("strong", { text: row.cell }), el("br"),
                      el("small", { class: "mono", text: c.scope })]),
        el("td", { text: DOMAIN_LABEL[c.domain] || c.domain }),
        name,
        el("td", { class: "dn", text: c.subject }),
        el("td", { class: "dn", text: c.issuer }),
        used,
        actions
      ]));
    });
    var empty = $("empty");
    empty.hidden = shown.length > 0;
    empty.textContent = state.rows.length
      ? "Aucun certificat ne correspond aux filtres." + (f.onlyDue ? " Rien n'arrive à échéance dans les " +
        config.renew_within_days + " jours : décochez « À échéance seulement » pour tout voir." : "")
      : "";
  }

  // -- the launch dialog -------------------------------------------------

  var pending = null;

  function field(label, input) {
    return el("label", {}, [label, input]);
  }

  function openDialog(row, action) {
    var c = row.cert;
    pending = { row: row, action: action, inputs: {} };
    $("dlg-title").textContent = ACTION[action].title;
    $("dlg-what").textContent = ACTION[action].what;
    var dl = $("dlg-cert");
    dl.textContent = "";
    [["Cellule", row.cell], ["Keystore", c.keystore + " (" + c.scope + ")"], ["Alias", c.alias],
     ["Sujet", c.subject], ["Émetteur", c.issuer],
     ["Expire le", (c.not_after || "?") + (row.days === null ? "" : " — " + row.days + " jours")]]
      .forEach(function (pair) {
        dl.appendChild(el("dt", { text: pair[0] }));
        dl.appendChild(el("dd", { text: pair[1] }));
      });
    var fields = $("dlg-fields");
    fields.textContent = "";
    if (action === "receive") {
      var alias = el("input", { type: "text", value: (c.pending_requests || [])[0] || "" });
      var signed = el("textarea", { placeholder: "-----BEGIN CERTIFICATE-----" });
      var ca = el("textarea", { placeholder: "Facultatif : le certificat de la CA émettrice, si la keystore ne l'a pas" });
      pending.inputs = { request_alias: alias, signed_certificate: signed, ca_certificate: ca };
      fields.appendChild(field("Alias de la requête", alias));
      fields.appendChild(field("Certificat signé par la CA (PEM)", signed));
      fields.appendChild(field("CA émettrice (PEM)", ca));
    }
    if (action === "refresh_signer") {
      var host = el("input", { type: "text", placeholder: "api.partenaire.example.com" });
      var port = el("input", { type: "number", value: "443", min: "1", max: "65535" });
      pending.inputs = { peer_host: host, peer_port: port };
      fields.appendChild(field("Hôte du pair", host));
      fields.appendChild(field("Port TLS", port));
    }
    $("dlg-force").checked = false;
    $("dlg-missing").hidden = true;
    var template = templateFor("renew", row.organization);
    $("dlg-launch").disabled = !template;
    if (!template) {
      $("dlg-missing").textContent = "Aucun job template de renouvellement n'est visible pour " +
        "l'organisation " + row.organization + " : il faut le droit de l'exécuter dans AWX.";
      $("dlg-missing").hidden = false;
    }
    $("dlg").showModal();
  }

  function values() {
    var out = { force: $("dlg-force").checked };
    Object.keys(pending.inputs).forEach(function (k) { out[k] = pending.inputs[k].value.trim(); });
    return out;
  }

  $("dlg-form").addEventListener("submit", function (event) {
    var submitter = event.submitter || {};
    if (submitter.value !== "launch" || !pending) return;
    var input = values();
    var gaps = C.missing(pending.action, input);
    if (gaps.length) {
      event.preventDefault();
      $("dlg-missing").textContent = "Il manque : " + gaps.join(", ") + ".";
      $("dlg-missing").hidden = false;
      return;
    }
    var row = pending.row;
    launch(templateFor("renew", row.organization), row.inventory,
           C.renewalVars(row, pending.action, input),
           ACTION[pending.action].title + " — " + row.cert.alias + " (" + row.cell + ")");
  });

  // -- jobs ----------------------------------------------------------------

  function launch(template, inventory, extraVars, label) {
    var entry = { label: label, id: null, status: "envoi…", template: template };
    state.jobs.unshift(entry);
    drawJobs();
    api("/job_templates/" + template.id + "/launch/", {
      method: "POST",
      body: { inventory: inventory, extra_vars: extraVars }
    }).then(function (answer) {
      entry.id = answer.job || answer.id;
      entry.status = answer.status || "pending";
      drawJobs();
      follow(entry);
    }).catch(function (err) {
      entry.status = "refusé";
      entry.error = err.login ? "Session AWX expirée : reconnectez-vous." : String(err.message || err);
      drawJobs();
    });
  }

  function follow(entry) {
    api("/jobs/" + entry.id + "/").then(function (job) {
      entry.status = job.status;
      if (!C.finished(job.status)) {
        drawJobs();
        setTimeout(function () { follow(entry); }, 3000);
        return;
      }
      entry.result = (job.artifacts || {}).wasevo_certificate_job || null;
      drawJobs();
      // A renewal ends with a fresh inventory of its cell, an inventory job is
      // one: either way the page now has something newer to show.
      if (job.status === "successful") refresh();
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

  function drawJobs() {
    $("jobs-section").hidden = state.jobs.length === 0;
    var list = $("jobs");
    list.textContent = "";
    state.jobs.forEach(function (entry) {
      var head = [el("strong", { text: entry.label }), " — " + (JOB_STATUS[entry.status] || entry.status)];
      if (entry.id) {
        head.push(" · ");
        head.push(el("a", { href: jobLink(entry.id), target: "_blank", rel: "noopener",
                            text: "job " + entry.id + " dans AWX" }));
      }
      var item = el("li", {}, [el("div", {}, head)]);
      if (entry.error) item.appendChild(el("p", { class: "error", text: entry.error }));
      var r = entry.result;
      if (r && r.action && !r.changed) {
        item.appendChild(el("p", { text: "Rien à faire : le certificat n'est plus à échéance, ou l'étape est déjà faite." }));
      }
      if (r && r.request_pem) {
        var copy = el("button", { type: "button", text: "Copier la requête" });
        copy.addEventListener("click", function () {
          if (navigator.clipboard) navigator.clipboard.writeText(r.request_pem);
        });
        item.appendChild(el("p", { text: "Requête " + r.request_alias +
          " à transmettre à la CA. Quand elle répond, utilisez « Recevoir » sur la ligne du certificat." }));
        item.appendChild(el("pre", { text: r.request_pem }));
        item.appendChild(copy);
      }
      list.appendChild(item);
    });
  }

  // -- wiring ----------------------------------------------------------------

  ["f-org", "f-domain", "f-due"].forEach(function (id) { $(id).addEventListener("change", drawRows); });
  $("f-text").addEventListener("input", drawRows);
  $("reload").addEventListener("click", refresh);
  $("login-link").setAttribute("href", (config.awx_ui || "/") + "#/login");

  fetch("portal.json", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .catch(function () { return {}; })
    .then(function (loaded) {
      Object.keys(loaded || {}).forEach(function (k) { config[k] = loaded[k]; });
      $("f-due-label").textContent = "À échéance seulement (≤ " + config.renew_within_days + " jours)";
      $("login-link").setAttribute("href", (config.awx_ui || "/") + "#/login");
      return refresh();
    });
})();
