import "@/styles/index.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";

import { createQueryClient } from "@/app/queryClient";
import { createRouter } from "@/app/router";
import { applyTheme, initialTheme } from "@/stores/ui";

applyTheme(initialTheme());

const container = document.getElementById("root");
if (!container) throw new Error("The #root element is missing from index.html.");

const queryClient = createQueryClient();
const router = createRouter();

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
