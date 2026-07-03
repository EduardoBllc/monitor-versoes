package services

import (
	"encoding/json"
	"fmt"
	"strings"

	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/ports"
)

const lockPath = "VERSAO.lock"

type lockTaskJSON struct {
	Task    string   `json:"task"`
	Titulo  string   `json:"titulo"`
	Commits []string `json:"commits"`
}

type lockExclusionJSON struct {
	Commit  string `json:"commit"`
	Chamado string `json:"chamado"`
	Motivo  string `json:"motivo"`
}

type lockJSON struct {
	Versao string `json:"versao"`
	Tipo   string `json:"tipo"`
	Base   struct {
		Ref    string `json:"ref"`
		Commit string `json:"commit"`
	} `json:"base"`
	Tasks     map[string]lockTaskJSON `json:"tasks"`
	Excluidos []lockExclusionJSON     `json:"excluidos"`
}

type LockStore struct{ Git ports.GitRepo }

func (s LockStore) Ler(branch string) (domain.Lock, error) {
	raw, err := s.Git.ReadFile(branch, lockPath)
	if err != nil {
		return domain.Lock{}, fmt.Errorf("lendo %s: %w", lockPath, err)
	}
	var lj lockJSON
	if err := json.Unmarshal(raw, &lj); err != nil {
		return domain.Lock{}, fmt.Errorf("parseando %s: %w", lockPath, err)
	}

	tipo, err := domain.InferirTipo(lj.Versao)
	if err != nil {
		return domain.Lock{}, err
	}

	tasks := domain.TargetSet{}
	for chamado, t := range lj.Tasks {
		var commits []domain.CommitRef
		for _, h := range t.Commits {
			commits = append(commits, domain.CommitRef{HashOrigem: h})
		}
		tasks[chamado] = domain.TaskTarget{Chamado: chamado, Task: t.Task, Titulo: t.Titulo, Commits: commits}
	}

	var excluidos []domain.Exclusion
	for _, e := range lj.Excluidos {
		excluidos = append(excluidos, domain.Exclusion{
			Commit: e.Commit, Chamado: e.Chamado, Motivo: e.Motivo, Reason: domain.ExclusaoAutomatica,
		})
	}

	return domain.Lock{
		Versao:    lj.Versao,
		Tipo:      tipo,
		Base:      domain.BaseRef{Ref: lj.Base.Ref, Commit: lj.Base.Commit},
		Tasks:     tasks,
		Excluidos: excluidos,
	}, nil
}

func (s LockStore) Escrever(branch string, lock domain.Lock) error {
	lj := lockJSON{Versao: lock.Versao, Tipo: tipoParaString(lock.Tipo), Tasks: map[string]lockTaskJSON{}}
	lj.Base.Ref = lock.Base.Ref
	lj.Base.Commit = lock.Base.Commit
	for chamado, t := range lock.Tasks {
		var hashes []string
		for _, c := range t.Commits {
			hashes = append(hashes, c.HashOrigem)
		}
		lj.Tasks[chamado] = lockTaskJSON{Task: t.Task, Titulo: t.Titulo, Commits: hashes}
	}
	for _, e := range lock.Excluidos {
		lj.Excluidos = append(lj.Excluidos, lockExclusionJSON{Commit: e.Commit, Chamado: e.Chamado, Motivo: e.Motivo})
	}

	raw, err := json.MarshalIndent(lj, "", "  ")
	if err != nil {
		return fmt.Errorf("serializando %s: %w", lockPath, err)
	}
	return s.Git.WriteFile(branch, lockPath, raw, "atualiza "+lockPath)
}

func tipoParaString(t domain.VersionType) string {
	switch t {
	case domain.VersionFechada:
		return "fechada"
	case domain.VersionAjustada:
		return "ajustada"
	default:
		return "cliente"
	}
}

// Reconstruir varre os trailers de cherry-pick em base..branch e regenera o
// lock (§3). `anterior`, se fornecido, e usado so pra apontar exclusoes por
// julgamento que nao dao pra recuperar da varredura - viram orfaos.
func (s LockStore) Reconstruir(branch string, base domain.BaseRef, versao string, anterior *domain.Lock) (domain.Lock, []domain.Exclusion, error) {
	commits, err := s.Git.CommitsInRange(base.Ref, branch)
	if err != nil {
		return domain.Lock{}, nil, fmt.Errorf("varrendo commits: %w", err)
	}

	tipo, err := domain.InferirTipo(versao)
	if err != nil {
		return domain.Lock{}, nil, err
	}

	tasks := domain.TargetSet{}
	for _, c := range commits {
		origemHash, ok := extrairTrailer(c.Msg)
		if !ok {
			continue // commit sem trailer -x: nao reconstruivel (dependencia dura, §3)
		}
		origemMeta, err := s.Git.CommitMeta(origemHash)
		if err != nil {
			continue // origem sumiu do historico
		}
		chamado, temChamado := domain.ExtrairChamado(origemMeta.Msg)
		vbID, temVB := domain.ExtrairVBID(origemMeta.Msg)
		if !temChamado && !temVB {
			continue
		}
		chave := chamado
		if chave == "" {
			chave = vbID
		}
		tt := tasks[chave]
		tt.Chamado = chamado
		if temVB {
			tt.Task = vbID
		}
		tt.Commits = append(tt.Commits, domain.CommitRef{
			HashOrigem: origemHash, Chamado: chamado, Task: vbID,
			CommitDate: origemMeta.CommitDate, Msg: origemMeta.Msg,
		})
		tasks[chave] = tt
	}

	lock := domain.Lock{Versao: versao, Tipo: tipo, Base: base, Tasks: tasks}

	var orfaos []domain.Exclusion
	if anterior != nil {
		for _, e := range anterior.Excluidos {
			if e.Reason == domain.ExclusaoJulgamento {
				orfaos = append(orfaos, e)
			}
		}
	}
	return lock, orfaos, nil
}

func extrairTrailer(msg string) (hash string, ok bool) {
	const marca = "(cherry picked from commit "
	i := strings.Index(msg, marca)
	if i < 0 {
		return "", false
	}
	resto := msg[i+len(marca):]
	fim := strings.IndexByte(resto, ')')
	if fim < 0 {
		return "", false
	}
	return resto[:fim], true
}
