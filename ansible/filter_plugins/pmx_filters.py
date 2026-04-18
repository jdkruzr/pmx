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


class FilterModule:
    """Ansible filter module."""

    def filters(self) -> dict[str, object]:
        """Return available filters."""
        return {"pmx_parse_cephfs": pmx_parse_cephfs}
