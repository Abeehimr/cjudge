import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import type { ReactNode } from "react";

export function renderRoute(element: ReactNode, path: string) {
  const router = createMemoryRouter([{ path: '*', element }], { initialEntries: [path] });
  return { ...render(<RouterProvider router={router} />), router };
}
