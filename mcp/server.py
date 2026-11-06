"""`arcade deploy` runs this. One server, one toolkit (Bank): see bank_tools/__init__.py."""

import sys

from bank_tools import app

if __name__ == "__main__":
    if len(sys.argv) > 1:
        app.run(transport=sys.argv[1])
    else:
        app.run()
