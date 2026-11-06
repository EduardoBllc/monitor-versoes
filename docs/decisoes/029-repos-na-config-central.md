# Repos na config central

- **Status:** aceita
- **Data:** 2026-11-05
- **Depende de:** [016](016-multi-projeto-premissas.md), [024](024-config-por-projeto.md)

O uso é local e há um operador por instalação. Nessa premissa, descobrir o repo por
`PROJECTS_DIR`, basename e aliases, e ler um `.monitor-versoes.toml` dentro de cada clone,
só espalhava o que o operador já sabe e controla num lugar só.

- **Repos são seções `[repos.<nome>]` do `config.toml` central**, com `caminho` obrigatório
  (`~` expandido). `--repo` recebe só o nome da seção; o nome é a identidade do repo no
  estado, então não aceita path.
- **Duas camadas, topo e seção**, mescladas chave a chave com a seção vencendo. O `piso` só
  vale na seção: um piso no topo valeria para repos de projetos diferentes, o que o
  [016](016-multi-projeto-premissas.md) já descartava.
- **Saem o `.monitor-versoes.toml` e os aliases.** O arquivo por clone obrigava a commitar
  config do operador no repo-alvo, e o alias existia para dois clones com nome diferente
  virarem o mesmo repo; com o nome escolhido na seção, quem decide a identidade é o operador.
- **O import path (`modulo:Classe`) vale em qualquer camada.** A restrição da
  [024](024-config-por-projeto.md) protegia contra um repo-alvo escolher o código a executar;
  sem o arquivo no clone, tudo o que é lido é do operador.
- **A linha `repo` do estado nasce no primeiro uso.** Não há cadastro: a seção na config é
  o cadastro. Estado de um nome sem seção é aviso do `motor diagnostico`, não erro.
