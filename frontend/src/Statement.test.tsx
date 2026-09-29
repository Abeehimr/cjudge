import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import Statement from "./Statement";

afterEach(cleanup);

test("optional Markdown stays hidden; script links, HTML and remote images do not render", () => {
  const empty = render(<Statement text="   " />);
  expect(screen.queryByLabelText("Task statement")).toBeNull();
  empty.unmount();
  render(<Statement text={'# Sum\n\n**Add** numbers. <script>alert(1)</script>\n\n[unsafe](javascript:alert(1)) [safe](https://example.org) ![remote](https://example.org/tracker.png)'} />);
  expect(screen.getByRole("heading", { name: "Sum" })).toBeTruthy();
  expect(screen.getByText("Add")).toBeTruthy();
  expect(screen.getByRole("link", { name: "safe" }).getAttribute("href")).toBe("https://example.org");
  expect(screen.getByText("unsafe").getAttribute("href")).toBe("");
  expect(screen.queryByRole("img")).toBeNull();
  expect(screen.getByLabelText("Task statement").querySelector("script")).toBeNull();
});
