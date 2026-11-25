import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { StatusProvider } from "./status";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Falta el elemento #root");

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <StatusProvider>
        <App />
      </StatusProvider>
    </BrowserRouter>
  </StrictMode>,
);
