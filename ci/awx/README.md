# AWX — what it holds, declared through its API

**EN** — AWX is hosted elsewhere: this repository no longer installs it and needs no Kubernetes. These scripts declare, through AWX's API, what it must hold to build and configure the WAS cell on the AIX server (`inventories/aix`, ServeurAIX). They run from any host that reaches AWX, need `bash`, `curl` and `python3`, and are re-runnable: every object is found by name and patched.

**FR** — AWX est hébergé ailleurs : ce dépôt ne l'installe plus et n'a besoin d'aucun Kubernetes. Ces scripts déclarent, par l'API d'AWX, ce qu'il doit contenir pour construire et configurer la cellule WAS sur le serveur AIX (`inventories/aix`, ServeurAIX). Ils tournent depuis n'importe quel hôte qui joint AWX, demandent `bash`, `curl` et `python3`, et sont rejouables : chaque objet est retrouvé par son nom et mis à jour.

```sh
export AWX_API=https://<awx>/api/v2
export AWX_TOKEN_FILE=~/.awx-token          # optional / optionnel

bash ci/awx/apply-cell-workflow.sh          # 1. inventory, templates 0-8, workflow, survey
bash ci/awx/apply-templates.sh              # 2. configuration templates 9-23 + WAS credential type
bash ci/awx/apply-survey.sh                 #    (run by 1) the survey and the Job type prompt
AWX_ORGANIZATION="Client A" AWX_INVENTORY="Client A - WAS" \
    bash ci/awx/apply-certificates.sh       # certificate templates, per organisation
```

| Variable | Default | |
|---|---|---|
| `AWX_API` | `https://awx.example.internal/api/v2` | **to set** / **à renseigner** |
| `AWX_TOKEN_FILE` | — | file holding a personal access token; sent as `Authorization: Bearer` / fichier contenant un jeton d'accès personnel |
| `AWX_USER` | `admin` | without a token, its password is typed at the prompt / sans jeton, son mot de passe est saisi à l'invite |
| `AWX_CA_FILE` | — | CA certificate to verify AWX; without it `curl -k` / certificat d'autorité pour vérifier AWX ; sans lui `curl -k` |

**Network / Réseau** — every call is `curl -sS -k --noproxy '*'`. AWX is reached directly: through the site's HTTP proxy its API answers **504 Gateway Timeout**. / Chaque appel est `curl -sS -k --noproxy '*'`. AWX est joint en direct : à travers le proxy HTTP du site, son API répond **504 Gateway Timeout**.

**Secrets** — the token or password never reaches a command line: it is written to a `0600` file (header or netrc) in a temporary directory made by Python's `tempfile.mkdtemp`, removed on exit. No script creates a credential that holds a secret; the machine credential "ServeurAIX (ansible)" and the "WAS administrative user" credential are made by hand in AWX, once. / Le jeton ou le mot de passe n'atteint jamais une ligne de commande : il est écrit dans un fichier `0600` (en-tête ou netrc) d'un répertoire temporaire créé par `tempfile.mkdtemp` de Python, supprimé à la sortie. Aucun script ne crée de credential portant un secret ; la credential machine « ServeurAIX (ansible) » et la credential « WAS administrative user » sont créées à la main dans AWX, une fois.

See README section 20. / Voir la section 20 du README.
