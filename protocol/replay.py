import time
from collections import OrderedDict
from protocol.mfa_option import MFACredential

class ReplayDefender:
    """Verifica se uma credencial MFA e um replay (nonce duplicado ou timestamp fora da janela)."""

    def __init__(self, tolerance: int = 30, cache_size: int = 10000):
        self.tolerance = tolerance
        self.cache = OrderedDict()  # (agent_id, nonce): timestamp
        self.cache_size = cache_size

    def is_valid(self, cred: MFACredential) -> bool:
        """Retorna True se a credencial for válida e não for um replay."""
        now = int(time.time())
        
        # 1. Validação temporal
        if abs(now - cred.timestamp) > self.tolerance:
            return False
        
        # 2. Validação de nonce (anti-replay)
        key = (cred.agent_id, cred.nonce)
        if key in self.cache:
            return False
            
        # Adiciona ao cache
        self.cache[key] = cred.timestamp
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
            
        return True
