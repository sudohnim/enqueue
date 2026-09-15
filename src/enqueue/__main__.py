"""Run the CLI as `python -m enqueue`.

The bundled desktop app launches the engine this way: it points a vendored, relocatable
Python at `-m enqueue serve`. Invoking the module (rather than the `enq` console script)
avoids the console script's absolute-path shebang, which breaks the moment the bundle is
copied into `Enqueue.app` at a different path.
"""

from .cli import app

if __name__ == "__main__":
    app()
