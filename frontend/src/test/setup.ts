// Матчеры jest-dom (toBeInTheDocument и т. п.) для Vitest + Testing Library.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Без globals:true авто-очистка RTL не регистрируется — чистим DOM между тестами сами.
afterEach(() => cleanup());
