import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { OnboardingExit } from "./onboarding-exit";

it("submits logout as browser navigation so an onboarding account can end its Keycloak session", () => {
  render(<OnboardingExit />);
  const button = screen.getByRole("button", { name: "Выйти" });
  expect(button).toHaveAttribute("type", "submit");
  expect(button.closest("form")).toHaveAttribute("action", "/api/auth/logout");
  expect(button.closest("form")).toHaveAttribute("method", "post");
});
