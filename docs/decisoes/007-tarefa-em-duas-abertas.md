# Tarefa marcada em duas versões abertas é dado inconsistente, não erro fatal

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md)

O motor sinaliza e pinta vermelho, mas o comando termina normal. **Duas abertas**, ao pé da
letra: a liberada é fonte de alvo mas não disputa ambiguidade, porque não compete por nada —
já saiu. Sem esse recorte, todo chamado remarcado à mão para contornar o buraco descrito em
[005](005-alvo-distribuicao-entre-versoes.md) (liberada fora da união) passaria a pintar a
versão de vermelho, e limpar isso é trabalho manual no Tickio numa versão já liberada.
