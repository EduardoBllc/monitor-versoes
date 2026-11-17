import type {
  ChamadoConsultado,
  CommitRef,
  VersionStatus,
} from "../../api/tipos";

export enum MotivoCommit {
  PRESENTE = "presente",
  FALTA = "falta",
  CONFLITA = "conflita",
  SUSPEITO = "suspeito",
}

export interface CommitVisto {
  hash: string;
  titulo: string;
  motivo: MotivoCommit | null;
  dependeDe: string[];
}

export interface ChamadoVisto {
  chamado: string;
  estado: string;
  commits: CommitVisto[];
  semCommits: boolean;
}

const hashes = (lista?: CommitRef[]): Set<string> =>
  new Set((lista ?? []).map((c) => c.hash_origem));

// Conflitantes e suspeitos também estão em faltantes: o motivo mais específico vence.
function motivos(status: VersionStatus): (hash: string) => MotivoCommit | null {
  const ordem: [Set<string>, MotivoCommit][] = [
    [hashes(status.conflitantes), MotivoCommit.CONFLITA],
    [hashes(status.suspeitos_conteudo), MotivoCommit.SUSPEITO],
    [hashes(status.faltantes), MotivoCommit.FALTA],
    [hashes(status.ancestrais), MotivoCommit.PRESENTE],
  ];
  return (hash) => ordem.find(([lista]) => lista.has(hash))?.[1] ?? null;
}

export function verChamados(
  chamados: ChamadoConsultado[],
  status: VersionStatus | null,
): ChamadoVisto[] {
  const motivo = status ? motivos(status) : () => null;
  return chamados.map((c) => ({
    chamado: c.chamado,
    estado: c.estado,
    semCommits: c.commits.length === 0,
    commits: c.commits.map((x) => ({
      hash: x.hash_origem,
      titulo: x.msg.split("\n")[0] ?? "",
      motivo: motivo(x.hash_origem),
      dependeDe: status?.conflito_causado_por?.[x.hash_origem] ?? [],
    })),
  }));
}

export function filtrarChamados(
  lista: ChamadoVisto[],
  estado: string | null,
  busca: string,
): ChamadoVisto[] {
  const termo = busca.trim().toLowerCase();
  return lista.filter(
    (c) =>
      (estado === null || c.estado === estado) &&
      (termo === "" ||
        c.chamado.toLowerCase().includes(termo) ||
        c.commits.some(
          (x) =>
            x.hash.toLowerCase().startsWith(termo) ||
            x.titulo.toLowerCase().includes(termo),
        )),
  );
}
