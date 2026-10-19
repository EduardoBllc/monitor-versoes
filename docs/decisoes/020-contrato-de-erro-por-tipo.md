# O contrato de erro é por tipo, não por texto

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [018](018-portas-e-adaptadores.md)

Adapter levanta `MotorError` ou subclasse, e nada mais. Quatro subclasses no eixo
das portas (`RecusaDeInvariante`, `NaoEncontrado`, `BackendIndisponivel`,
`RespostaInvalida`) e uma no eixo do operador (`ErroDeEntrada`).

**Por que tipo e não mensagem.** A suíte de contrato casava substring em
português — `match="imutavel"` em seis lugares. É o mesmo acoplamento que o
`_traduzir_erro` já tinha e consertou (passou a casar `errcode = 'MV001'` em vez
de `"imutavel" in str(e.orig)`), e reprovaria um adapter correto que escrevesse
"immutable".

**O que não ganha classe.** Falha genérica de passagem (`git …: exit status N`)
fica `MotorError` puro: o site não sabe o que falhou, e adivinhar é pior que não
classificar. Bug de programação levanta `AssertionError`, que já cai no caminho
de traceback do `main()`.

**Só `MotorError` degrada.** Os services capturam `MotorError`, não `Exception`.
Antes o oráculo de presença engolia qualquer coisa e devolvia `AUSENTE` — um bug
no adapter virava veredito de presença errado, em silêncio.

**Contexto por `add_note()`, não por embrulho.** `raise MotorError(f"buscando
tasks: {e}")` achatava a subclasse na fronteira em que o chamador mais precisa
dela. A nota preserva o tipo — mas **não** chega sozinha ao operador:
`__notes__` só aparece em traceback renderizado, e para `MotorError` os dois
front-ends imprimem uma linha limpa, sem traceback. Por isso os handlers de
`MotorError` do `__main__` e da TUI concatenam `__notes__` na linha que
imprimem, com teste afirmando a linha visível. Descobrir isso custou uma
revisão: a primeira versão desta decisão afirmava que o contexto continuava
chegando, e não conferiu.
