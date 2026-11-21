#!/usr/bin/env python3
"""The imcl templates must render what the servers actually use.

inventories/aix/response_files/<env>/<level>/*.xml are the response files
rebuilt from the servers. For each of them, this renders every component the
matching server declares in inventories/aix/config/<env>.yml, through
inventories/aix/templates/imcl/, and compares what Installation Manager reads:
the variables, every profile (id, installLocation, data keys), every offering
(profile, id, version, features) and the preferences. Whitespace, comments and
the order of profiles do not count - imcl ignores them; anything else does.

The server a reference file belongs to is the longest server key of the
environment's config that its name starts with: dev-was-01_WAS_Ihs_Plugins_...
belongs to dev-was-01.

    python3 ci/check-imcl-templates.py [inventories/aix]

Exit 0 when every file matches, 1 with the differences otherwise.
"""
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

import jinja2
import yaml

INV = sys.argv[1] if len(sys.argv) > 1 else "inventories/aix"


def load_group_vars():
    """group_vars/all, top-level strings resolved against each other."""
    ctx = {"inventory_dir": INV}
    for f in sorted(glob.glob(os.path.join(INV, "group_vars", "all", "*.yml"))):
        with open(f, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for k, v in data.items():
            if not k.startswith("vault_"):
                ctx[k] = v
    env = jinja2.Environment()
    for _ in range(6):
        for k, v in list(ctx.items()):
            if isinstance(v, str) and "{{" in v:
                try:
                    ctx[k] = env.from_string(v).render(**ctx)
                except Exception:
                    pass
    return ctx


def model(text):
    """What imcl reads from a response file, order-free."""
    root = ET.fromstring(text.encode("utf-8"))
    variables = sorted((v.get("name"), v.get("value")) for v in root.iter("variable"))
    profiles = sorted(
        (p.get("id"), p.get("installLocation"),
         tuple(sorted((d.get("key"), d.get("value")) for d in p.iter("data"))))
        for p in root.findall("profile"))
    offerings = sorted(
        (o.get("profile"), o.get("id"), o.get("version"), o.get("features"))
        for o in root.iter("offering"))
    prefs = sorted((p.get("name"), p.get("value")) for p in root.iter("preference"))
    return variables, profiles, offerings, prefs


def main():
    ctx = load_group_vars()
    loader = jinja2.FileSystemLoader(os.path.join(INV, "templates", "imcl"))
    env = jinja2.Environment(loader=loader, trim_blocks=True, undefined=jinja2.StrictUndefined)
    failures, checked = [], 0

    for ref in sorted(glob.glob(os.path.join(INV, "response_files", "*", "*", "*.xml"))):
        env_dir = ref.split(os.sep)[-3]
        cfg_file = os.path.join(INV, "config", env_dir + ".yml")
        with open(cfg_file, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        servers = cfg.get("imcl_servers") or {}
        stem = os.path.basename(ref).split("_response_file")[0]
        keys = [k for k in servers if stem.startswith(k)]
        name = os.path.relpath(ref, INV)
        if not keys:
            failures.append(f"{name}: no server of config/{env_dir}.yml matches it")
            continue
        server = max(keys, key=len)
        level = ctx["imcl_levels"][cfg.get("imcl_level", ctx["imcl_default_level"])]

        rendered = [[], [], [], []]
        for comp, entry in servers[server].items():
            spec = ctx["imcl_component_catalog"][comp]
            text = env.get_template(spec["template"]).render(
                **ctx, **cfg, _entry=entry, _level=level)
            for acc, part in zip(rendered, model(text)):
                acc.extend(part)
        # Variables and preferences repeat once per component file: compare
        # them as sets, profiles and offerings as lists.
        got = (sorted(set(rendered[0])), sorted(rendered[1]),
               sorted(rendered[2]), sorted(set(rendered[3])))
        with open(ref, encoding="utf-8") as fh:
            want = model(fh.read())

        checked += 1
        labels = ("variables", "profiles", "offerings", "preferences")
        for label, w, g in zip(labels, want, got):
            if list(w) != list(g):
                missing = [x for x in w if x not in g]
                extra = [x for x in g if x not in w]
                failures.append(f"{name} ({server}): {label} differ\n"
                                f"    missing: {missing}\n    extra:   {extra}")

    for f in failures:
        print("FAIL", f)
    print(f"{checked} reference file(s) checked, {len(failures)} difference(s)")
    return 1 if failures or checked == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
