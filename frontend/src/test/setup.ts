// Матчеры jest-dom (toBeInTheDocument и т. п.) для Vitest + Testing Library.
import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// Дефолтный asyncUtilTimeout у waitFor/findBy — 1000мс: под нагрузкой CI (166 тест-файлов,
// ограниченный CPU) тяжёлые RTL-файлы иногда его превышают → редкий флейк. Даём запас.
configure({ asyncUtilTimeout: 5000 });

// Без globals:true авто-очистка RTL не регистрируется — чистим DOM между тестами сами.
afterEach(() => cleanup());
