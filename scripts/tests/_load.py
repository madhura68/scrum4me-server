import importlib.machinery
import importlib.util
import os

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rotate-env-credential")


def load():
    loader = importlib.machinery.SourceFileLoader("rotate_env_credential", SCRIPT)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
