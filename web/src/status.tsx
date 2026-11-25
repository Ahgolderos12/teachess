import { createContext, type ReactNode, useContext } from "react";

import { api } from "./api";
import { useAsync } from "./hooks";
import type { Status } from "./types";

interface StatusContextValue {
  status: Status | null;
  error: string | null;
  reload: () => void;
}

const StatusContext = createContext<StatusContextValue>({
  status: null,
  error: null,
  reload: () => undefined,
});

export function StatusProvider({ children }: { children: ReactNode }) {
  const { data, error, reload } = useAsync(() => api.status(), []);
  return (
    <StatusContext.Provider value={{ status: data, error, reload }}>
      {children}
    </StatusContext.Provider>
  );
}

export const useStatus = () => useContext(StatusContext);
