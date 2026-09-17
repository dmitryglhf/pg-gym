import type { ChatModel } from "@/lib/chat-models.ts";
import { Field } from "../PlatformUI.tsx";

export function ModelPicker(
  { label, value, other, models, disabled, onChange, optional = false }: {
    label: string;
    value: string;
    other: string;
    models: ChatModel[];
    disabled: boolean;
    onChange: (value: string) => void;
    optional?: boolean;
  },
) {
  const selectedOther = models.find((model) => model.key === other);
  const groups = [
    {
      label: "Downloaded models",
      items: models.filter((model) => model.artifact?.kind === "model"),
    },
    {
      label: "Trained variants",
      items: models.filter((model) => model.artifact?.kind === "adapter"),
    },
    {
      label: "API connections",
      items: models.filter((model) => !model.artifact),
    },
  ];
  return (
    <Field label={label}>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        <option value="">{optional ? "Single model" : "Select a model"}</option>
        {value && !models.some((model) => model.key === value) && (
          <option value={value}>Selected model is unavailable</option>
        )}
        {groups.filter((group) => group.items.length).map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.items.map((model) => (
              <option
                key={model.key}
                value={model.key}
                disabled={model.key === other ||
                  (!!model.connection &&
                    model.connection.id === selectedOther?.connection?.id)}
              >
                {model.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </Field>
  );
}
