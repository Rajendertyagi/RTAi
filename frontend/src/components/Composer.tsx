import { useRef, useState, type KeyboardEvent, type ChangeEvent } from "react";
import { useChat } from "../state/ChatContext";
import { Dropdown } from "./Dropdown";
import { AttachIcon, FocusIcon, StopIcon, AgentIcon, ModelIcon, ThinkingIcon, SendIcon } from "./Icons";

function cap(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function Composer() {
  const { state, sendPrompt, cancel, selectAgent, selectModel, setThinking } = useChat();
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const value = text.trim();
    if (!value || state.generating) return;
    sendPrompt(value);
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onInput = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  };

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
    <div className="composer">
      <div className="composer-card">
        <div className="composer-body">
          <textarea
            ref={taRef}
            className="composer-input"
            id="input"
            rows={2}
            placeholder="Ask anything... (Shift+Enter for newline)"
            value={text}
            onChange={onInput}
            onKeyDown={onKeyDown}
          />
        </div>
        <div className="composer-footer">
          <div className="footer-left">
            <button className="ctrl-btn" title="Attach file" type="button">
              <AttachIcon />
            </button>
            <button className="ctrl-btn" title="Focus mode" type="button">
              <FocusIcon />
            </button>
          </div>
          <div className="footer-right">
            {state.generating && (
              <button className="ctrl-btn" id="stopBtn" title="Stop" type="button" onClick={cancel}>
                <StopIcon />
              </button>
            )}
            <Dropdown
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
            <button className="send-btn" id="sendBtn" title="Send" type="button" onClick={submit}>
              <SendIcon />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
