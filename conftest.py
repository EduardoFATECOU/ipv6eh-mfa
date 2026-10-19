# -*- coding: utf-8 -*-
"""Permite rodar ``pytest`` de qualquer diretório.

Os pacotes do projeto (``protocol``, ``ml``, ``attacks``, ``eval``, ...) sao
importados a partir da raiz deste repositorio. Sem este ``conftest.py``, o
``pytest`` so funciona quando executado com o CWD dentro de ``implementacao/``
(porque ``python -m pytest`` coloca o CWD no ``sys.path``).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
