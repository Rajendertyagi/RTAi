import React from "react";
import { useChat } from "../state/ChatContext";
import { Dropdown } from "./Dropdown";
import { AgentIcon, ModelIcon, ThinkingIcon } from "./Icons";

function cap(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/**
 * Agent / Model / Thinking pickers for the composer footer.
 *
 * Memoised on purpose: the composer re-renders on every keystroke while the
 * user types, but these controls depend only on global state (the capability
 * lists), never on the textarea contents.
 */
function ModelControlsImpl() {
  const { state, selectAgent, selectModel, setThinking } = useChat();
  const { agents, models, thinkingLevels } = state.capabilities;
  const selectedAgent = agents.find((a) => a.id === state.selectedAgent);
  const selectedModel = models.find((m) => m.id === state.selectedModel);

  // When the backend marks a section unavailable it sends no items at all, so
  // surface its reason rather than leaving a dead, silent control behind.
  const reasonFor = (section: "agents" | "models" | "thinking") => {
    const why = state.capabilities.unavailable[section];
    if (why) return `${why.message} (${why.code})`;
    return `No ${section === "thinking" ? "thinking levels" : section} available. Connect to a project folder first.`;
  };

  return (
    <>
      <Dropdown
        className="ctrl-btn has-label"
        title="Agent"
        disabled={agents.length === 0}
        disabledReason={reasonFor("agents")}
        trigger={
          <>
            <AgentIcon />
            <span className="btn-label">{selectedAgent?.label ?? "Agent"}</span>
          </>
        }
        items={agents}
        activeId={state.selectedAgent}
        onSelect={selectAgent}
      />
      <Dropdown
        className="ctrl-btn has-label"
        title="Model"
        disabled={models.length === 0}
        disabledReason={reasonFor("models")}
        trigger={
          <>
            <ModelIcon />
            <span className="btn-label">{selectedModel?.label ?? "Model"}</span>
          </>
        }
        items={models}
        activeId={state.selectedModel}
        onSelect={selectModel}
      />
      <Dropdown
        className="ctrl-btn has-label"
        title="Thinking"
        disabled={thinkingLevels.length === 0}
        disabledReason={reasonFor("thinking")}
        trigger={
          <>
            <ThinkingIcon />
            <span className="btn-label">{cap(state.thinkingLevel)}</span>
          </>
        }
        items={thinkingLevels.map((l) => ({ id: l, label: cap(l) }))}
        activeId={state.thinkingLevel}
        onSelect={setThinking}
      />
    </>
  );
}

export const ModelControls = React.memo(ModelControlsImpl);
