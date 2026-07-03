package domain

import (
	"regexp"
	"sort"
)

var padraoChamado = regexp.MustCompile(`\bch(\d+)\b`)
var padraoVB = regexp.MustCompile(`\b(VB-\d+)\b`)

// MatchExato filtra candidatos de grep por word-boundary - ch<num> e VB-<num>
// exatos, nao substring (§4 "Precisao do match"). search_commits do GitRepo so
// traz candidatos brutos.
func MatchExato(candidatos []CommitRef, chamado, vbID string) []CommitRef {
	var padroes []*regexp.Regexp
	if chamado != "" {
		padroes = append(padroes, regexp.MustCompile(`\bch`+regexp.QuoteMeta(chamado)+`\b`))
	}
	if vbID != "" {
		padroes = append(padroes, regexp.MustCompile(`\b`+regexp.QuoteMeta(vbID)+`\b`))
	}

	var resultado []CommitRef
	for _, c := range candidatos {
		for _, p := range padroes {
			if p.MatchString(c.Msg) {
				resultado = append(resultado, c)
				break
			}
		}
	}
	return resultado
}

// ExtrairChamado acha um numero de chamado (ch<num>) na mensagem, usado na
// reconstrucao do lock (§3) para reagrupar por chamado a partir do trailer.
func ExtrairChamado(msg string) (chamado string, ok bool) {
	m := padraoChamado.FindStringSubmatch(msg)
	if m == nil {
		return "", false
	}
	return m[1], true
}

// ExtrairVBID acha um id VB-<num> na mensagem.
func ExtrairVBID(msg string) (vbID string, ok bool) {
	m := padraoVB.FindStringSubmatch(msg)
	if m == nil {
		return "", false
	}
	return m[1], true
}

// OrdenarPorData ordena por CommitDate asc - nao depende de flag do git (§5
// "Ordenacao"). Nao muta a fatia de entrada.
func OrdenarPorData(commits []CommitRef) []CommitRef {
	ordenado := make([]CommitRef, len(commits))
	copy(ordenado, commits)
	sort.Slice(ordenado, func(i, j int) bool {
		return ordenado[i].CommitDate.Before(ordenado[j].CommitDate)
	})
	return ordenado
}
