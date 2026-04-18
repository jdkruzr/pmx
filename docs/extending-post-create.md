# Extending the post-create hook

`ansible/roles/post_create_hook` runs as the final task of the configure play
and is the designated extension point for anything that should fire after a
guest is successfully built: DHCP reservations, DNS records, monitoring
registration, chat-ops notifications, etc.

## Variables available to the role

The guest is the Ansible host during this role, so `ansible_host`,
`ansible_facts`, etc. are all available. Additionally the following extra-vars
are set:

| Variable              | Type             | Notes                                             |
| --------------------- | ---------------- | ------------------------------------------------- |
| `guest_name`          | str              | Hostname / pmx primary key                        |
| `guest_vmid`          | int              | Proxmox VMID                                      |
| `guest_mac`           | str              | Primary NIC MAC                                   |
| `guest_kind`          | "vm" \| "lxc"   | Creation path taken                               |
| `guest_os`            | "ubuntu" \| "rocky" | OS family                                     |
| `domain_join`         | bool             | Whether AD join was performed                     |
| `cephfs_mounts`       | list[str]        | Raw `--cephfs` specs                              |
| `rbd_disk`            | int \| null      | Extra RBD disk size in GiB                        |
| `extra_packages`      | list[str]        | Operator-supplied packages                        |
| `static_ip`           | str \| null      | Static IP CIDR, or null for DHCP                  |
| `static_gw`           | str \| null      | Explicit gateway, or null for inferred .1         |
| `ad_domain`           | str              | e.g. "broken.wrx"                                 |
| `ad_realm`            | str              | e.g. "BROKEN.WRX"                                 |
| `state_log_path`      | str              | Absolute path to `state/guests.jsonl`             |

## Adding a new extension

Create a task file next to `tasks/main.yml` (e.g. `tasks/dhcp_zentyal.yml`) and
include it conditionally:

```yaml
- name: Register DHCP reservation with Zentyal
  ansible.builtin.include_tasks: dhcp_zentyal.yml
  delegate_to: localhost
  become: false
  when: dhcp_reservations_enabled | default(false)
```

Add a defaults entry so the feature is off-by-default:

```yaml
# defaults/main.yml
dhcp_reservations_enabled: false
```

Flip it on in `~/.config/pmx/config.yml` (needs a new loader field) or pass
`-e dhcp_reservations_enabled=true`.

## Contract guarantees

The role always runs last in the configure play. It must NEVER mutate guest
state; it only makes calls to external systems (Zentyal, DNS, monitoring) and
writes to the workstation's state log. If a new extension mutates the guest,
it belongs in a different role, not here.

## State log format

`state/guests.jsonl` is append-only JSON Lines. Each line is one dict with
the fields listed above plus `created_at` (ISO8601 UTC). Reader API lives in
`pmx/state.py`.
