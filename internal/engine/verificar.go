package engine

import (
	"monitor-versoes/internal/domain"
	"monitor-versoes/internal/services"
)

// Verificar implementa a operacao read-only do §5: cruza ClickUp x lock x git
// e retorna o VersionStatus. Nunca muta nada.
func Verificar(d Deps, versao string) (domain.VersionStatus, error) {
	resolver := services.TargetResolver{Tasks: d.Tasks, Git: d.Git}
	alvo, err := resolver.Resolve(versao)
	if err != nil {
		return domain.VersionStatus{}, err
	}

	lockStore := services.LockStore{Git: d.Git}
	lock, err := lockStore.Ler(versao)
	if err != nil {
		return domain.VersionStatus{}, err
	}

	alvoFiltrado := domain.FiltrarExcluidos(alvo, lock.Excluidos)

	todosOsHashes := map[string]domain.CommitRef{}
	candidatosConflito := map[string]bool{}
	for _, tt := range alvoFiltrado {
		for _, c := range tt.Commits {
			todosOsHashes[c.HashOrigem] = c
			candidatosConflito[c.HashOrigem] = true
		}
	}
	for _, tt := range lock.Tasks {
		for _, c := range tt.Commits {
			if _, ja := todosOsHashes[c.HashOrigem]; !ja {
				todosOsHashes[c.HashOrigem] = c
			}
		}
	}

	oracle := services.PresenceOracle{Git: d.Git}
	tip, err := d.Git.ResolveRef(versao)
	if err != nil {
		return domain.VersionStatus{}, err
	}

	presentes := map[string]bool{}
	var conflitantes []domain.CommitRef
	for hash, c := range todosOsHashes {
		ok, err := oracle.Presente(hash, lock.Base.Ref, versao)
		if err != nil {
			return domain.VersionStatus{}, err
		}
		presentes[hash] = ok
		// PredictMerge so faz sentido pra commits que sao candidatos reais de
		// cherry-pick (lado alvo) - Conflitantes e subconjunto de Faltantes
		// (domain.VersionStatus), nunca de commits sumidos so-no-lock.
		if !ok && candidatosConflito[hash] {
			meta, err := d.Git.CommitMeta(hash)
			if err != nil {
				return domain.VersionStatus{}, err
			}
			pred, err := d.Git.PredictMerge(meta.Parent, tip, hash)
			if err != nil {
				return domain.VersionStatus{}, err
			}
			if pred.Conflita {
				conflitantes = append(conflitantes, c)
			}
		}
	}

	return domain.Reconciliar(alvoFiltrado, lock, presentes, conflitantes), nil
}
