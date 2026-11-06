import { Alert, List, MantineProvider, Title } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Metodo, api } from "./api/cliente";
import type { components } from "./api/esquema";

type RepoOption = components["schemas"]["RepoOption"];

const queryClient = new QueryClient();

function Repos() {
  const { data, error } = useQuery({
    queryKey: ["repos"],
    queryFn: () => api<RepoOption[]>(Metodo.GET, "/api/repos"),
  });
  if (error) return <Alert color="red">{error.message}</Alert>;
  return (
    <List>
      {data?.map((repo) => (
        <List.Item key={repo.nome}>{repo.nome}</List.Item>
      ))}
    </List>
  );
}

export function App() {
  return (
    <MantineProvider defaultColorScheme="auto">
      <QueryClientProvider client={queryClient}>
        <Notifications />
        <Title order={2} m="md">
          monitor-versões
        </Title>
        <Repos />
      </QueryClientProvider>
    </MantineProvider>
  );
}
