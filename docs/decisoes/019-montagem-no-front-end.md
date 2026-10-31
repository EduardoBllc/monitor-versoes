# Quem monta os adapters é o front-end, nunca o engine

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [018](018-portas-e-adaptadores.md)

`motor/montagem.py` é o único módulo que conhece adapter concreto e `Deps` ao mesmo tempo.
CLI e TUI importam dele; o engine vê só `motor.ports`. A camada existe porque a alternativa
apareceu nas duas formas ruins: um `if token: PR senão grep` dentro do `verificar` (engine
importando `motor.adapters`), ou a mesma regra duplicada nos dois front-ends. Com dois
front-ends, "montar no chamador" precisa de um lugar só — e esse lugar não é o engine.

**Montar não é usar.** Nada na montagem faz I/O: não valida credencial, não consulta o git.
`atualizar --abort` e `reconstruir-estado` recebem as mesmas fontes e nunca as chamam — se a
montagem tocasse a rede ou o git, todo comando pagaria por elas, e um clone sem `origin`
passaria a falhar antes de começar. Por isso o `workspace/repo` do Bitbucket sai do remote na
primeira busca, dentro do adapter, e não na construção. Única exceção deliberada:
`resolver_repo`, porque o nome canônico e o `tickio_sistema_id` decidem _como_ montar o resto.

`motor diagnostico` não abre exceção na montagem: o I/O dele (conexão ao banco, autenticação no
Tickio e no Bitbucket) fica em `motor/diagnostico.py` e em métodos de verificação públicos dos
adapters, e a montagem segue sem tocar rede nem banco. "Montar não é usar" vale para os demais
comandos.

Consequência de teste: as bordas de I/O se trocam em `motor.montagem`, não no front-end. Um
`monkeypatch` no módulo do CLI não alcança mais a montagem da TUI, e é justamente esse o
ponto — antes as duas se ligavam por um import de nome privado.
