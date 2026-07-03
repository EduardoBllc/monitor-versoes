package domain

import (
	"fmt"
	"strconv"
	"strings"
)

func parseVersao(numero string) (x, y, z int, err error) {
	partes := strings.Split(numero, ".")
	if len(partes) != 3 {
		return 0, 0, 0, fmt.Errorf("versao %q: esperado formato X.Y.Z", numero)
	}
	nums := make([]int, 3)
	for i, p := range partes {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return 0, 0, 0, fmt.Errorf("versao %q: componente %q invalido", numero, p)
		}
		nums[i] = n
	}
	return nums[0], nums[1], nums[2], nil
}

func InferirTipo(numero string) (VersionType, error) {
	_, y, z, err := parseVersao(numero)
	if err != nil {
		return 0, err
	}
	switch {
	case y == 0 && z == 0:
		return VersionFechada, nil
	case z == 0:
		return VersionAjustada, nil
	default:
		return VersionCliente, nil
	}
}

// InferirBase resolve a base de uma versao (§7). versoesExistentes e a lista de
// branches de versao ja existentes (ex.: vindas de GitRepo.ListVersionBranches).
func InferirBase(numero string, versoesExistentes []string) (string, error) {
	x, y, z, err := parseVersao(numero)
	if err != nil {
		return "", err
	}
	if y == 0 && z == 0 {
		return "master", nil
	}
	if z == 0 {
		for cand := y - 1; cand >= 0; cand-- {
			candidato := fmt.Sprintf("%d.%d.0", x, cand)
			if contains(versoesExistentes, candidato) {
				return candidato, nil
			}
		}
		return "", fmt.Errorf("nenhuma base X.Y.0 encontrada abaixo de %s", numero)
	}
	candidato := fmt.Sprintf("%d.%d.%d", x, y, z-1)
	if contains(versoesExistentes, candidato) {
		return candidato, nil
	}
	return fmt.Sprintf("%d.%d.0", x, y), nil
}

func contains(lista []string, alvo string) bool {
	for _, v := range lista {
		if v == alvo {
			return true
		}
	}
	return false
}
