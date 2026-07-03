package domain

import "time"

type VersionType int

const (
	VersionFechada  VersionType = iota // X.0.0
	VersionAjustada                    // X.Y.0
	VersionCliente                     // X.Y.Z
)

type BaseRef struct {
	Ref    string // "13.6.0"
	Commit string // hash
}

type Version struct {
	Numero string // "13.7.0"
	Tipo   VersionType
	Base   BaseRef
}

type CommitRef struct {
	HashOrigem string
	Parent     string // pai do commit na branch de origem (necessario pra PredictMerge)
	Chamado    string // "255514"
	Task       string // "VB-2354"
	CommitDate time.Time
	Msg        string
}

type TaskTarget struct {
	Chamado string // numero do chamado — chave externa
	Task    string // "VB-xxxx"
	Titulo  string
	Commits []CommitRef
}

// TargetSet = task->commits resolvido (§4). Chave = chamado.
type TargetSet map[string]TaskTarget

type ExclusionReason int

const (
	ExclusaoAutomatica ExclusionReason = iota // recomputavel via Presente()
	ExclusaoJulgamento                        // irredutivel, so existe no lock
)

type Exclusion struct {
	Commit  string
	Chamado string
	Motivo  string
	Reason  ExclusionReason
}

type Lock struct {
	Versao    string
	Tipo      VersionType
	Base      BaseRef
	Tasks     TargetSet
	Excluidos []Exclusion
}

type VersionStatus struct {
	Verde          bool
	TasksNovas     []string // em ClickUp, fora do lock
	TasksRemovidas []string // no lock, fora do ClickUp
	LockIntegro    bool
	CommitsSumidos []string // no lock, ausentes no git
	Faltantes      []CommitRef
	Conflitantes   []CommitRef // subconjunto de Faltantes que da conflito (merge-tree)
}
