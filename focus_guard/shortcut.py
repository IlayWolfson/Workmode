"""Create a Desktop shortcut with a custom icon (PowerShell and WScript.Shell)."""

import subprocess
from collections.abc import Callable


def _quote(text: object) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def build_script(name: str, target: str, arguments: str, workdir: str, icon: str, folder: str = "Desktop") -> str:
    """folder: a .NET special folder name, "Desktop" or "Startup"."""
    return "\n".join(
        [
            f"$folder = [Environment]::GetFolderPath({_quote(folder)})",
            f"$path = Join-Path $folder {_quote(name + '.lnk')}",
            "$shell = New-Object -ComObject WScript.Shell",
            "$link = $shell.CreateShortcut($path)",
            f"$link.TargetPath = {_quote(target)}",
            f"$link.Arguments = {_quote(arguments)}",
            f"$link.WorkingDirectory = {_quote(workdir)}",
            f"$link.IconLocation = {_quote(str(icon) + ',0')}",
            "$link.Save()",
            "Write-Output $path",
        ]
    )


def create_shortcut(
    name: str,
    target: str,
    arguments: str,
    workdir: str,
    icon: str,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    folder: str = "Desktop",
) -> str:
    result = run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            build_script(name, target, arguments, workdir, icon, folder),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "could not create the shortcut")
    return result.stdout.strip()
