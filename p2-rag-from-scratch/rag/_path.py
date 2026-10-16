"""Make the repository's shared/ package importable.

The projects in this repository are directories with hyphens in their names,
which cannot be Python package names, so they are not importable as a package
tree and `python -m bench.run` has to be run from inside the project. That
leaves the repository root off sys.path, and shared/ with it.

Putting the root on the path here is the least ceremonious fix. The alternative
is packaging each project and installing it editable, which is a lot of
machinery for six small projects that each run from one directory.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
