"""
migrar_admins_pra_sheet.py — Fase E §5.93.

Lê os 3 admins do config.yaml local e os cadastra na aba Clientes da
Google Sheet, **preservando os hashes bcrypt existentes** (logo, as
senhas atuais `nava`/`fagundes`/`caruso` continuam funcionando).

Nome/sobrenome inferidos do email (parte antes do @ dividida por ponto).
Empresa hardcoded como "Bradesco BBI". Código sequencial ADMIN-001 etc.

Idempotente: se um admin já existe na Sheet (mesmo email), pula sem
modificar — não duplica.

Como rodar (da raiz do projeto):
  venv/Scripts/python.exe scripts/migrar_admins_pra_sheet.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from yaml.loader import SafeLoader

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.google_sheets import (  # noqa: E402
    adicionar_cliente,
    buscar_cliente_por_email,
)


CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
EMPRESA_ADMIN = "Bradesco BBI"


def _split_email(email: str) -> tuple[str, str]:
    """Extrai (nome, sobrenome) do email BBI.

    Ex: 'francisco.navarrete@bradescobbi.com.br' → ('Francisco', 'Navarrete')
        'joao.fagundes@bradescobbi.com.br' → ('Joao', 'Fagundes')

    Se email não tem ponto no local-part, sobrenome fica vazio.
    """
    local = email.split("@", 1)[0]
    partes = local.split(".", 1)
    nome = partes[0].title()
    sobrenome = partes[1].replace(".", " ").title() if len(partes) > 1 else ""
    return nome, sobrenome


def main() -> int:
    print("=" * 70)
    print("  MIGRAR ADMINS DO config.yaml -> Aba Clientes (Google Sheets)")
    print("=" * 70)

    if not CONFIG_PATH.exists():
        print(f"ERRO: {CONFIG_PATH} nao encontrado.")
        return 1

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.load(f, Loader=SafeLoader)

    usernames = cfg.get("credentials", {}).get("usernames", {})
    if not usernames:
        print("Nenhum admin no config.yaml.")
        return 1

    print(f"\nAdmins encontrados no config.yaml: {len(usernames)}")
    for u in usernames:
        print(f"  - {u}")

    print("\nMigrando...")
    sucessos = 0
    pulados = 0
    erros = 0
    for i, (email, info) in enumerate(sorted(usernames.items()), start=1):
        codigo = f"ADMIN-{i:03d}"
        nome, sobrenome = _split_email(email)
        senha_hash = info.get("password", "")

        if not senha_hash.startswith("$2b$"):
            print(f"  [SKIP] {email}: hash bcrypt invalido")
            erros += 1
            continue

        # Idempotencia: ja cadastrado?
        existente = buscar_cliente_por_email(email)
        if existente is not None:
            print(f"  [PULA] {email}: ja na Sheet com codigo "
                  f"{existente.get('codigo')!r}")
            pulados += 1
            continue

        try:
            adicionar_cliente(
                codigo=codigo,
                nome=nome,
                sobrenome=sobrenome,
                empresa=EMPRESA_ADMIN,
                email=email,
                senha_hash=senha_hash,
            )
            print(f"  [OK]   {codigo} | {nome} {sobrenome} | {email}")
            sucessos += 1
        except Exception as e:
            print(f"  [ERRO] {email}: {type(e).__name__}: {e}")
            erros += 1

    print()
    print("=" * 70)
    print(f"  Sucesso: {sucessos}  |  Pulados (ja existia): {pulados}  "
          f"|  Erros: {erros}")
    print("=" * 70)
    return 0 if erros == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
