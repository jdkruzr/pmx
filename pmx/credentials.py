"""AD credential handling for pmx.

The AD join password is prompted once per shell session, cached in
`$AD_JOIN_PASSWORD`, and reused by subsequent pmx invocations. On a
fresh shell the user is prompted (hidden input); a hint is printed
showing how to export the password for future shells if desired.
"""

from __future__ import annotations

import getpass
import os

import click

ENV_VAR = "AD_JOIN_PASSWORD"


def ensure_ad_password() -> str:
    """Return the AD join password, prompting if not already cached.

    The returned value is also exported into os.environ[ENV_VAR] so
    downstream subprocess calls (ansible-playbook) inherit it.
    """
    cached = os.environ.get(ENV_VAR)
    if cached:
        return cached

    password = getpass.getpass(prompt="AD join password (jtd@broken.wrx): ")
    if not password:
        click.echo("No password entered; aborting.", err=True)
        raise click.Abort()

    os.environ[ENV_VAR] = password
    click.echo(
        f"Cached credential for this process. "
        f"To reuse across shells: export {ENV_VAR}=<password>",
        err=True,
    )
    return password
