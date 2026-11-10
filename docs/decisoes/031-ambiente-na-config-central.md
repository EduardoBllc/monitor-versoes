# Ambiente na config central

- **Status:** aceita
- **Data:** 2026-11-10
- **Depende de:** [024](024-config-por-projeto.md), [028](028-inscricoes-fora-do-estado.md),
  [029](029-repos-na-config-central.md)

O `.env` só era lido do diretório atual. Com banco, Bitbucket e credenciais da fonte de
tarefas nele, o motor só funcionava de um diretório, e as inscrições precisavam guardar esse
diretório para a execução agendada achá-lo. Com os repos já no `config.toml` central
([029](029-repos-na-config-central.md)), o ambiente era a última peça presa ao diretório.

- **O ambiente é da instalação, e por isso fica no central, só no topo.** A tabela
  `[ambiente]` do `config.toml` guarda banco e credenciais. Uma `[repos.<nome>.ambiente]` é
  erro: banco e credenciais não variam por repo, e aceitar a seção sugeriria que variam.
- **Os nomes são os das variáveis de ambiente.** O motor exporta cada par para o ambiente do
  processo antes de montar o parser, então adapters, plugins e os defaults das flags enxergam o
  valor sem mudar. Chaves tipadas por assunto (`[banco] backend`) seriam mais legíveis, mas
  obrigariam cada plugin a aprender a lê-las; o motor não conhece as credenciais dos plugins.
- **Precedência: `[ambiente]` > `.env` do diretório atual > shell.** O `.env` continua como
  alternativa, para quem já o tem. O central vence também o `.env.development` do
  `--env development`, de propósito: quem configura a instalação no central não deve cair num
  banco por causa do diretório em que está. Quem desenvolve não põe `[ambiente]` no central da
  máquina, ou aponta `XDG_CONFIG_HOME` para outro lugar. Flag explícita continua vencendo,
  porque é da invocação e não do ambiente.
- **O arquivo central é achado pelo ambiente herdado.** Um `XDG_CONFIG_HOME` vindo do `.env`
  ou do próprio `[ambiente]` mudaria qual arquivo se lê no meio da leitura; ele é descartado.
- **A inscrição não guarda diretório nem `--env`.** O filho do `inscricao rodar` não lê `.env`
  nenhum e aplica o `[ambiente]` sobre o ambiente do agendador; a execução agendada não depende
  de onde a inscrição foi criada. Um central inválido vira desfecho de erro da inscrição, e não
  uma execução com meia configuração, que poderia cair noutro banco. Inscrições antigas com os
  dois campos continuam sendo lidas, e os campos são ignorados.
- **O `motor init` não escreve `.env`.** O `compose.yml` do Postgres tem valores padrão iguais
  aos do exemplo de `[ambiente]` e sobe sem `.env`.
