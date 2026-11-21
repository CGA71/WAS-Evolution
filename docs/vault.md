# Le mot de passe de `was` dans le vault / The `was` password in the vault

> **FR** — Procédure pour enregistrer le mot de passe du compte `was` dans un vault Ansible, le faire ouvrir par AWX, et le changer.
>
> **EN** — How to store the `was` account's password in an Ansible vault, have AWX open it, and change it. The English summary is at the end.

## Pourquoi

Sur les serveurs WAS AIX, trois comptes, trois rôles :

| Compte | D'où il vient | Pour quoi |
|---|---|---|
| Compte de connexion | le nom d'utilisateur de la **credential Machine AWX** — l'inventaire ne fixe aucun `ansible_user` | ouvrir la session SSH |
| `root` | le compte de connexion lance `sudo su -` | ce qui change le **système** : monter le partage des binaires, l'arborescence, les paquets et les limites AIX (rôles `binaries_share`, `prereqs_os`) |
| `was` | le compte de connexion lance `su - was`, avec **le mot de passe de `was`** | tout ce qui **construit, configure ou modifie WebSphere** : installation, fix packs, profils, cluster, ressources, démarrage |

`was` n'a **aucun droit sudo** et n'en utilise jamais : les deux élévations partent toujours du compte de connexion, jamais l'une de l'autre. C'est [`inventories/aix/group_vars/was_servers.yml`](../inventories/aix/group_vars/was_servers.yml) qui les règle ; une tâche qui doit passer root le déclare (`vars: {wasevo_become_as: root}`), toutes les autres passent `was`.

Le mot de passe de `was` ne doit apparaître **en clair nulle part** : ni dans le dépôt, ni dans AWX, ni dans un log. Il vit dans un fichier chiffré du dépôt, `inventories/aix/group_vars/all/90_vault.yml`, et seul AWX détient la clé qui l'ouvre.

```
inventories/aix/group_vars/all/00_site.yml    site_was_password: "{{ vault_site_was_password }}"   (en clair : une référence)
inventories/aix/group_vars/all/90_vault.yml   vault_site_was_password: "..."                       (chiffré)
AWX, credential de type Vault « aix »         le mot de passe qui ouvre 90_vault.yml
```

## 1. Créer le fichier chiffré

Une seule fois, sur une machine qui a `ansible-core` — Linux, WSL, ou le serveur AWX ; pas un poste Windows seul. Sur la branche `features` :

```sh
cd WAS-Evolution
git checkout features && git pull

ansible-vault create --vault-id aix@prompt inventories/aix/group_vars/all/90_vault.yml
```

`ansible-vault` demande deux fois le **mot de passe du vault**. Ce n'est **pas** celui de `was` : c'est une clé que vous choisissez, longue, et qui ira dans le coffre-fort de l'équipe. Puis il ouvre un éditeur ; saisir, et enregistrer :

```yaml
---
vault_site_was_password: "le mot de passe de was"
```

**Si `sudo su -` demande un mot de passe** au compte de connexion (règle sudoers sans `NOPASSWD`), ajouter aussi :

```yaml
vault_site_root_become_password: "le mot de passe du compte de connexion"
```

C'est nécessaire parce que le mot de passe de `was`, déclaré dans l'inventaire, prend le pas sur le *Privilege Escalation Password* de la credential Machine : AWX ne peut plus le fournir pour `sudo`. Si la règle est `NOPASSWD`, ne rien ajouter.

## 2. Vérifier, puis commiter

```sh
head -1 inventories/aix/group_vars/all/90_vault.yml
# $ANSIBLE_VAULT;1.2;AES256;aix          <- chiffré : on peut commiter

git add inventories/aix/group_vars/all/90_vault.yml
git commit -m "AIX: the was password, vaulted"
git push origin features
```

Si la première ligne n'est pas `$ANSIBLE_VAULT;...`, le fichier est en clair : **ne pas le commiter**, le supprimer et recommencer l'étape 1.

## 3. Donner la clé à AWX

1. **Resources → Credentials → Add**.
2. *Name* : `WAS AIX vault` ; *Credential Type* : **Vault**.
3. *Vault Password* : le mot de passe du vault choisi à l'étape 1.
4. *Vault Identifier* : `aix` — le même que dans `--vault-id aix@prompt`.
5. **Save**.

Puis l'attacher à **chaque job template `WAS AIX - …`** : *Edit* → *Credentials* → ajouter `WAS AIX vault` **à côté** de la credential Machine (un job template accepte une credential Machine et une credential Vault ensemble). Resynchroniser le projet pour qu'AWX lise le nouveau fichier.

## 4. Vérifier que chaque élévation arrive où elle doit

Depuis une machine qui a le dépôt, la clé SSH du compte de connexion et la clé du vault :

```sh
# WebSphere : doit répondre uid=...(was)
ansible -i inventories/aix was_install -u <compte de connexion> -b -m command -a id \
    --vault-id aix@prompt

# Système : doit répondre uid=0(root)
ansible -i inventories/aix was_install -u <compte de connexion> -b -m command -a id \
    --vault-id aix@prompt -e wasevo_become_as=root
```

Dans AWX, la même vérification : un job *ad hoc* (*Inventories → l'inventaire AIX → Run Command*), module `command`, argument `id`, *Enable privilege escalation* coché, avec les deux credentials.

Échecs habituels :

| Message | Cause |
|---|---|
| `'vault_site_was_password' is undefined` | la credential Vault n'est pas attachée au job template, ou son identifiant n'est pas `aix` |
| `Decryption failed` | mauvais mot de passe de vault dans la credential AWX |
| `Incorrect su password` | le mot de passe de `was` dans le vault est faux, ou `was` n'accepte pas `su` (attribut AIX `su`, `sugroups`) |
| `Timeout (12s) waiting for privilege escalation prompt` | `sudo su -` demande un mot de passe que le vault ne fournit pas : voir l'étape 1, `vault_site_root_become_password` |

## 5. Changer un mot de passe

```sh
# le mot de passe de was (ou du compte de connexion) : on édite, on commite
ansible-vault edit --vault-id aix@prompt inventories/aix/group_vars/all/90_vault.yml
git commit -am "AIX: the was password, rotated" && git push origin features

# la clé du vault elle-même : on la change, puis on met à jour la credential AWX
ansible-vault rekey --vault-id aix@prompt --new-vault-id aix@prompt \
    inventories/aix/group_vars/all/90_vault.yml
git commit -am "AIX: vault rekeyed" && git push origin features
```

Pour lire le contenu sans l'éditer : `ansible-vault view --vault-id aix@prompt …/90_vault.yml`.

## Ce qu'il ne faut jamais faire

- commiter `90_vault.yml` en clair, ou un fichier `.vault_pass` contenant la clé ;
- passer le mot de passe par `-e was_password=...` en ligne de commande, ou en variable d'extra vars d'un job template : il apparaît dans l'historique et dans AWX ;
- écrire la clé du vault dans le dépôt, un ticket ou un message : elle va dans le coffre-fort de l'équipe, et dans la credential AWX.

Avant toute publication publique du dépôt, `90_vault.yml` est chiffré mais reste un secret : il doit figurer parmi les chemins retirés par le script de publication.

---

## English summary

**Three accounts.** The **connecting** account is the AWX Machine credential's (the inventory sets no `ansible_user`). **root** is reached through `sudo su -`, only for system tasks — mounting the share, directories, AIX packages and limits (`binaries_share`, `prereqs_os`), each marked `vars: {wasevo_become_as: root}`. Everything that **builds, configures or changes WebSphere** runs as **`was`**, through `su - was` with its own password. `was` never uses sudo. See [`was_servers.yml`](../inventories/aix/group_vars/was_servers.yml).

**Steps.**

1. `ansible-vault create --vault-id aix@prompt inventories/aix/group_vars/all/90_vault.yml` and write `vault_site_was_password: "..."` — plus `vault_site_root_become_password` if `sudo su -` asks for a password, since the inventory's become password outranks the AWX credential's.
2. Check the first line reads `$ANSIBLE_VAULT;1.2;AES256;aix`, then commit and push.
3. In AWX, create a **Vault** credential, identifier `aix`, holding the vault password; attach it to every `WAS AIX - …` job template beside the Machine credential.
4. Verify with `ansible … -b -m command -a id --vault-id aix@prompt`: `uid=…(was)`, and `uid=0(root)` with `-e wasevo_become_as=root`.
5. Rotate with `ansible-vault edit` (a password) or `ansible-vault rekey` (the vault key, then update the AWX credential).

Never commit the file in clear, never pass the password as an extra var, never write the vault key anywhere but the team's password safe and the AWX credential.
