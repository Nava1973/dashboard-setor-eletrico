"""
gen_password.py
Gera hash bcrypt de uma senha para colar no config.yaml.

Uso:
    python gen_password.py
    > Digite a senha: ********
    > Hash: $2b$12$...

Copie o hash e cole no campo `password:` do usuário em config.yaml.
"""

import getpass
import streamlit_authenticator as stauth


def main():
    senha = getpass.getpass("Digite a senha: ")
    senha2 = getpass.getpass("Confirme a senha: ")
    if senha != senha2:
        print("❌ Senhas não coincidem.")
        return
    if len(senha) < 8:
        print("⚠️  Senha curta (< 8 caracteres). Considere algo mais forte.")
    # streamlit-authenticator >= 0.4 usa a classe Hasher com método estático hash
    try:
        hashed = stauth.Hasher.hash(senha)
    except AttributeError:
        # Compatibilidade com versões < 0.4
        hashed = stauth.Hasher([senha]).generate()[0]
    print("\nCole este hash no campo `password:` do usuário em config.yaml:\n")
    print(hashed)


if __name__ == "__main__":
    main()
