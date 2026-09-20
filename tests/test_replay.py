import time
import pytest
from protocol.mfa_option import MFACredential
from protocol.replay import ReplayDefender

@pytest.fixture
def defender():
    return ReplayDefender(tolerance=30)

def create_cred(timestamp, nonce, agent_id=1):
    return MFACredential(
        factor_type=1,
        version=1,
        confidence=0.5,
        timestamp=timestamp,
        agent_id=agent_id,
        nonce=nonce,
        raw=b""
    )

def test_valid_credential(defender):
    now = int(time.time())
    cred = create_cred(now, 100)
    assert defender.is_valid(cred)

def test_replay_duplicate_nonce(defender):
    now = int(time.time())
    cred1 = create_cred(now, 100)
    cred2 = create_cred(now + 1, 100)  # Mesmo nonce, timestamp diferente (ainda é replay pelo nonce)
    
    assert defender.is_valid(cred1)
    assert not defender.is_valid(cred2)

def test_stale_timestamp(defender):
    now = int(time.time())
    # 31 segundos atrás (fora da tolerância de 30s)
    cred = create_cred(now - 31, 200)
    assert not defender.is_valid(cred)

def test_future_timestamp(defender):
    now = int(time.time())
    # 31 segundos no futuro
    cred = create_cred(now + 31, 300)
    assert not defender.is_valid(cred)
