import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { Layout } from "./components/Layout";
import { ROUTES } from "./routes";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Retry once on network or server errors; a 4xx (not found, bad request, forbidden) will not change on retry.
      retry: (failures, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 1,
      refetchOnWindowFocus: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            {ROUTES.map(({ path, component: C }) => (
              <Route key={path} path={path} element={<C />} />
            ))}
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
