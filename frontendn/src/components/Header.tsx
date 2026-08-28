import { useChat } from "../state/ChatContext";
import { Dropdown } from "./Dropdown";
import { ModelIcon } from "./Icons";

export function Header() {
  const { state, selectModel } = useChat();
  const { models } = state.capabilities;
  const selectedModel = models.find((m) => m.id === state.selectedModel);
  const selectedThinking = thinkingLevels.find((l) => l === state.thinkingLevel);

  return (
    <header className="header">
      <div className="header-title" id="headerTitle">
        {state.headerTitle || "Current Session"}
      </div>
      <div className="header-controls">
        <Dropdown
          className="model-picker"
          title="Select model"
          trigger={
            <>
              <ModelIcon />
              <span id="modelName">{selectedModel?.label ?? "Select Model"}</span>
            </>
          }
          items={models}
          activeId={state.selectedModel}
          onSelect={selectModel}
        />
      </div>
    </header>
  );
}
