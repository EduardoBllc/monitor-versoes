# Disparo das inscrições pelo daemon

- **Status:** aceita
- **Data:** 2026-11-14
- **Depende de:** [028](028-inscricoes-fora-do-estado.md), [031](031-ambiente-na-config-central.md),
  [032](032-lock-por-repo-entre-processos.md)

Com o `serve` de pé, uma thread do daemon dispara as inscrições vencidas: roda na subida e a
cada 60 s, e uma rodada que falha é logada sem derrubar o laço. O motor deixa de instalar o
agendador do SO: o objetivo é não haver nada a configurar além de subir o daemon.

- **Cada inscrição segue num processo próprio** ([028](028-inscricoes-fora-do-estado.md)), em
  sessão própria: o Ctrl+C no terminal do `serve` não chega ao filho, que termina e grava o
  resultado. O shutdown do daemon não espera filho em curso, que pode durar até 1 h.
- **O filho não herda o `.env` do `serve`.** O daemon repassa o ambiente capturado antes de
  aplicar o `.env` do diretório, e o filho reaplica sozinho o `[ambiente]` central
  ([031](031-ambiente-na-config-central.md)).
- **Quem não usa o daemon agenda o `inscricao rodar` à mão**, pelo agendador que preferir.
- **Usar os dois, ou dois `serve` em portas diferentes, dobra o disparo.** Não há corrupção: a
  segunda execução sai `pulada` pelo lock do clone
  ([032](032-lock-por-repo-entre-processos.md)).
