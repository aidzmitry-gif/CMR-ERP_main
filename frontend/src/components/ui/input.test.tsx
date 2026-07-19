import { createRef } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Input, Textarea, Select, Field } from "./input";

describe("Input", () => {
  it("рендерит без иконки с классом обычной границы", () => {
    render(<Input placeholder="Имя" />);
    const el = screen.getByPlaceholderText("Имя");
    expect(el).toHaveClass("border-line-strong");
    expect(el).not.toHaveClass("pl-9");
  });

  it("рендерит с иконкой: добавляет pl-9 и оборачивает в relative-контейнер", () => {
    render(<Input icon={<span data-testid="icn">*</span>} placeholder="С иконкой" />);
    const el = screen.getByPlaceholderText("С иконкой");
    expect(el).toHaveClass("pl-9");
    expect(screen.getByTestId("icn")).toBeInTheDocument();
    expect(el.parentElement).toHaveClass("relative");
  });

  it("invalid=true применяет класс ошибки вместо обычного", () => {
    render(<Input invalid placeholder="Ошибка" />);
    const el = screen.getByPlaceholderText("Ошибка");
    expect(el).toHaveClass("border-[#F2C4C4]");
    expect(el).not.toHaveClass("border-line-strong");
  });

  it("прокидывает value/onChange и вызывает обработчик с введённым текстом", () => {
    let seenValue = "";
    const onChange = vi.fn((e) => {
      seenValue = e.target.value;
    });
    render(<Input value="" onChange={onChange} placeholder="Текст" />);
    fireEvent.change(screen.getByPlaceholderText("Текст"), { target: { value: "привет" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(seenValue).toBe("привет");
  });

  it("disabled запрещает ввод и добавляет соответствующий атрибут", () => {
    render(<Input disabled placeholder="Диз" />);
    const el = screen.getByPlaceholderText("Диз") as HTMLInputElement;
    expect(el).toBeDisabled();
  });

  it("forwardRef указывает на реальный DOM-элемент input", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input ref={ref} placeholder="Реф" />);
    expect(ref.current).toBeInstanceOf(HTMLInputElement);
    expect(ref.current?.placeholder).toBe("Реф");
  });

  it("пробрасывает пользовательский className дополнительно к базовым классам", () => {
    render(<Input className="my-custom-class" placeholder="Класс" />);
    const el = screen.getByPlaceholderText("Класс");
    expect(el).toHaveClass("my-custom-class");
    expect(el).toHaveClass("border-line-strong");
  });
});

describe("Textarea", () => {
  it("рендерит textarea с обычной границей и min-height классом", () => {
    render(<Textarea placeholder="Комментарий" />);
    const el = screen.getByPlaceholderText("Комментарий");
    expect(el.tagName).toBe("TEXTAREA");
    expect(el).toHaveClass("border-line-strong");
    expect(el).toHaveClass("min-h-[76px]");
  });

  it("invalid=true переключает класс границы на ошибочный", () => {
    render(<Textarea invalid placeholder="Плохо" />);
    expect(screen.getByPlaceholderText("Плохо")).toHaveClass("border-[#F2C4C4]");
  });

  it("вызывает onChange с введённым текстом", () => {
    let seenValue = "";
    const onChange = vi.fn((e) => {
      seenValue = e.target.value;
    });
    render(<Textarea onChange={onChange} placeholder="Ввод" />);
    fireEvent.change(screen.getByPlaceholderText("Ввод"), { target: { value: "текст" } });
    expect(seenValue).toBe("текст");
  });
});

describe("Select", () => {
  it("рендерит переданные опции и переключает выбранное значение", () => {
    render(
      <Select defaultValue="a" onChange={vi.fn()}>
        <option value="a">Первая</option>
        <option value="b">Вторая</option>
      </Select>,
    );
    const el = screen.getByRole("combobox") as HTMLSelectElement;
    expect(el.value).toBe("a");
    fireEvent.change(el, { target: { value: "b" } });
    expect(el.value).toBe("b");
  });

  it("invalid=true применяет ошибочный класс границы вместо обычного", () => {
    render(
      <Select invalid>
        <option value="x">X</option>
      </Select>,
    );
    const el = screen.getByRole("combobox");
    expect(el).toHaveClass("border-[#F2C4C4]");
    expect(el).not.toHaveClass("border-line-strong");
  });
});

describe("Field", () => {
  it("показывает label и звёздочку required", () => {
    render(
      <Field label="Название" required>
        <Input placeholder="п" />
      </Field>,
    );
    expect(screen.getByText("Название")).toBeInTheDocument();
    expect(screen.getByText("*")).toBeInTheDocument();
  });

  it("без required звёздочка не рендерится", () => {
    render(
      <Field label="Название">
        <Input placeholder="п" />
      </Field>,
    );
    expect(screen.queryByText("*")).not.toBeInTheDocument();
  });

  it("показывает error вместо hint, когда оба переданы", () => {
    render(
      <Field label="Поле" hint="подсказка" error="ошибка ввода">
        <Input placeholder="п" />
      </Field>,
    );
    expect(screen.getByText("ошибка ввода")).toBeInTheDocument();
    expect(screen.queryByText("подсказка")).not.toBeInTheDocument();
  });

  it("показывает hint, если error не передан", () => {
    render(
      <Field label="Поле" hint="просто подсказка">
        <Input placeholder="п" />
      </Field>,
    );
    expect(screen.getByText("просто подсказка")).toBeInTheDocument();
  });

  it("не рендерит блок label, если label не передан", () => {
    render(
      <Field>
        <Input placeholder="без лейбла" />
      </Field>,
    );
    expect(screen.queryByText("*")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("без лейбла")).toBeInTheDocument();
  });
});
