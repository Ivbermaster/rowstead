from .base import AdapterError
from .browser_demo import BrowserDemoAdapter
from .registry_demo import RegistryDemoAdapter

ADAPTERS = {"registry_demo": RegistryDemoAdapter(), "browser_demo": BrowserDemoAdapter()}

__all__ = ["ADAPTERS", "AdapterError"]
