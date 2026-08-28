import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ChangeEvent,
} from "react";
import { useChat } from "../state/ChatContext";
import type { CapabilityItem } from "../types/protocol";
import { useComposerDraft } from "../hooks/useComposerDraft";
import { ModelControls } from "./ModelControls";
import {
  AttachIcon,
  FocusIcon,
  StopIcon,
  SendIcon,
  AutoAcceptIcon,
} from "./Icons";

export function Composer() {
  const { state, sendPrompt, cancel, toggleAutoAccept } = useChat();
  const { text, setText, clearDraft } = useComposerDraft();
  const [highlight, setHighlight] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const value = text.trim();
    if (!value || state.generating) return;
    sendPrompt(value);
    clearDraft();
    if (taRef.current) taRef.current.style.height = "auto";
  };

  // Slash-command suggestions: active while the first token is still being
  // typed (leading "/" and no space yet).
  const isCommandMode = text.startsWith("/") && !text.includes(" ");
  const query = isCommandMode ? text.slice(1).toLowerCase() : "";
  const matches = isCommandMode
    ? state.capabilities.commands.filter((c) => c.label.toLowerCase().includes(query))
    : [];
  const commandOpen = matches.length > 0 && !dismissed;

  useEffect(() => {
    setHighlight(0);
  }, [query]);

  useEffect(() => {
    if (!isCommandMode) setDismissed(false);
  }, [isCommandMode]);

  // A restored draft can be taller than the default two rows.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, []);

  const applyCommand = (cmd: CapabilityItem) => {
    setText(`/${cmd.label} `);
    setDismissed(true);
    taRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (commandOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (h + 1) % matches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (h - 1 + matches.length) % matches.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        const picked = matches[Math.min(highlight, matches.length - 1)];
        if (picked) applyCommand(picked);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDismissed(true);
        return;
      }
    }
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

  const generating = state.generating;

  return (
    <div className="composer">
      <div className="composer-card">
        {commandOpen && (
          <div className="command-popup" role="listbox" aria-label="Slash commands">
            {matches.map((c, i) => (
              <div
                key={c.id}
                className={`command-item${i === highlight ? " active" : ""}`}
                role="option"
                aria-selected={i === highlight}
                // onMouseDown (not onClick) so the textarea keeps focus.
                onMouseDown={(e) => {
                  e.preventDefault();
                  applyCommand(c);
                }}
              >
                <span className="command-name">/{c.label}</span>
                {c.input_hint ? <span className="command-hint">{c.input_hint}</span> : null}
                {c.description ? <span className="command-desc">{c.description}</span> : null}
              </div>
            ))}
          </div>
        )}
        <div className="composer-body">
          <textarea
            ref={taRef}
            className="composer-input"
            id="input"
            rows={2}
            placeholder="Ask anything... (Shift+Enter for newline, / for commands)"
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
            <button
              className={`ctrl-btn${state.autoAccept ? " is-active" : ""}`}
              id="autoAcceptBtn"
              title={
                state.autoAccept
                  ? "Auto-accept permissions: ON — click to turn off"
                  : "Auto-accept permissions: OFF — click to answer prompts automatically"
              }
              aria-pressed={state.autoAccept}
              type="button"
              onClick={toggleAutoAccept}
            >
              <AutoAcceptIcon />
            </button>
          </div>
          <div className="footer-right">
            <ModelControls />
            <button
              className={`send-btn${generating ? " stop" : ""}`}
              id="sendBtn"
              title={generating ? "Stop" : "Send"}
              type="button"
              onClick={generating ? cancel : submit}
            >
              {generating ? <StopIcon /> : <SendIcon />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
