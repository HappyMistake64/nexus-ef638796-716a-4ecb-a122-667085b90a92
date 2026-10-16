"""One executable resolver shared by diagnostics, version capture and execution."""
import os
import shutil
import subprocess
from pathlib import Path

INSTALL = 'sudo apt-get update && sudo apt-get install -y sumo util-linux'


class DependencyError(RuntimeError):
    pass


def executable(name):
    if name not in ('sumo', 'netconvert', 'prlimit'):
        raise ValueError('Nepodporovaný nástroj')
    directory = os.environ.get('CITY_SUMO_BIN') if name != 'prlimit' else None
    candidate = str(Path(directory).expanduser().resolve() / name) if directory else name
    found = shutil.which(candidate)
    if not found:
        where = directory or 'PATH'
        raise DependencyError(
            f'Chybí spustitelný nástroj {name} ({where}). '
            f'Na Ubuntu spusťte: {INSTALL}. '
            'SUMO není Python balíček; pip install jej nenahradí. '
            'Pro vlastní instalaci nastavte CITY_SUMO_BIN na adresář se sumo a netconvert.'
        )
    return str(Path(found).resolve())


def versions():
    result = {}
    for name in ('sumo', 'netconvert', 'prlimit'):
        binary = executable(name)
        try:
            run = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DependencyError(f'Nelze spustit {binary} --version: {exc}') from exc
        result[name + '_version'] = run.stdout.strip()
    return result
