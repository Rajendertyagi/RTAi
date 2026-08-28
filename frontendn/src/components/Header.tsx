import { useChat } from "../state/ChatContext";
import { ModelIcon } from "./Icons";

export function Header() {
  const { state } = useChat();
  const { models, unavailable } = state.capabilities;
  const selectedModel = models.find((m) => m.id === state.selectedModel);

  // Read-only on purpose: the interactive Agent/Model/Thinking pickers all live
  // together in the composer footer. This chip only reports the current model.
  const label = selectedModel?.label ?? (unavailable.models ? "Models unavailable" : "No model");
  const title = unavailable.models
    ? `${unavailable.models.message} (${unavailable.models.code})`
    : "Selected model";

  return (
    <header className="header">
      <div className="header-title" id="headerTitle">
        {state.headerTitle || "Current Session"}
      </div>
      <span className="model-chip" id="modelName" title={title}>
        <ModelIcon />
        <span>{label}</span>
      </span>
    </header>
  );
}
