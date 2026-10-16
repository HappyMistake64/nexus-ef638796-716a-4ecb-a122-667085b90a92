"""Run with the same interpreter and environment as tests / desktop."""
import sys
from .tools import DependencyError, executable, versions


def main():
    print('Python:', sys.executable)
    errors = []
    for name in ('sumo', 'netconvert', 'prlimit'):
        try:
            print(name + ':', executable(name))
        except DependencyError as exc:
            errors.append(str(exc))
    if not errors:
        try:
            for key, value in versions().items():
                print(key + ':', value.splitlines()[0] if value else '(bez textu verze)')
        except DependencyError as exc:
            errors.append(str(exc))
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
