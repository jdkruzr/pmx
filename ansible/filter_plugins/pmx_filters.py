"""Filter plugins used by pmx roles."""

from __future__ import annotations


def pmx_parse_cephfs(spec: str) -> dict[str, str]:
    """Parse '<subpath>:<guest-path>' into {'subpath': ..., 'dest': ...}.

    >>> pmx_parse_cephfs('supernote:/mnt/sn')
    {'subpath': '/supernote', 'dest': '/mnt/sn'}
    """
    if ":" not in spec:
        raise ValueError(f"cephfs spec must be '<subpath>:<guest-path>', got: {spec!r}")
    subpath, dest = spec.split(":", 1)
    if not dest:
        raise ValueError(f"cephfs spec destination cannot be empty, got: {spec!r}")
    if not subpath.startswith("/"):
        subpath = "/" + subpath
    return {"subpath": subpath, "dest": dest}


def pmx_cephx_caps(specs: list[dict[str, str]], fs_name: str = "cephfs") -> dict[str, str]:
    """Least-privilege CephX caps for a client that mounts the given CephFS subpaths.

    Produces exactly the strings `ceph fs authorize <fs> <entity> <path> rw ...`
    writes, so `ceph auth get -f json` output compares equal to this and a
    reconfigure run can tell "unchanged" from "needs `ceph auth caps`".

    >>> pmx_cephx_caps([{'subpath': '/supernote', 'dest': '/mnt/sn'}])
    {'mds': 'allow rw fsname=cephfs path=/supernote', 'mon': 'allow r fsname=cephfs', 'osd': 'allow rw tag cephfs data=cephfs'}
    """
    clauses = []
    for spec in specs:
        subpath = spec["subpath"]
        clause = f"allow rw fsname={fs_name}"
        if subpath != "/":
            clause += f" path={subpath}"
        clauses.append(clause)
    return {
        "mds": ", ".join(clauses),
        "mon": f"allow r fsname={fs_name}",
        "osd": f"allow rw tag cephfs data={fs_name}",
    }


class FilterModule:
    """Ansible filter module."""

    def filters(self) -> dict[str, object]:
        """Return available filters."""
        return {"pmx_parse_cephfs": pmx_parse_cephfs, "pmx_cephx_caps": pmx_cephx_caps}
